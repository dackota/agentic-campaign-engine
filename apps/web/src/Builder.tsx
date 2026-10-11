import { useEffect, useMemo, useState } from "react";
import { listVersions, saveWorkflow, validateWorkflow, type Rejection } from "./builderApi";
import { messageOf } from "./messages";
import type { StepKind, Workflow, WorkflowStep } from "./workflow.gen";

const TEMPLATE_NAME = "Threat report to campaign";
const TEMPLATE: WorkflowStep[] = [
  { id: "email_draft", kind: "agent" },
  { id: "approval", kind: "approval" },
  { id: "publish", kind: "publish" },
];
const DEFAULT_WAIT_SECONDS = 60;
const NAME_PATTERN = /^[a-z0-9][a-z0-9-]{0,62}$/;

/** A chain: each step starts after the one above it. Reordering rewires the edges. */
export function toWorkflow(steps: WorkflowStep[]): Workflow {
  return {
    steps,
    edges: steps.slice(1).map((s, i) => ({ from: steps[i]!.id, to: s.id })),
  };
}

function freshId(steps: WorkflowStep[], kind: StepKind): string {
  const taken = new Set(steps.map((s) => s.id));
  if (!taken.has(kind)) return kind;
  let n = 2;
  while (taken.has(`${kind}_${n}`)) n += 1;
  return `${kind}_${n}`;
}

export function moveStep(steps: WorkflowStep[], from: number, to: number): WorkflowStep[] {
  const next = [...steps];
  const [moved] = next.splice(from, 1);
  if (!moved) return steps;
  next.splice(to, 0, moved);
  return next;
}

/** Set or clear one numeric step field; an empty box clears it. */
function withPolicy(step: WorkflowStep, field: "max_attempts" | "review_rounds", raw: string) {
  const next = { ...step };
  delete next[field];
  return raw.trim() === "" ? next : { ...next, [field]: Number(raw) };
}

interface StepRowProps {
  step: WorkflowStep;
  onChange: (step: WorkflowStep) => void;
  onRemove: () => void;
  dragProps: React.HTMLAttributes<HTMLLIElement>;
}

function StepRow({ step, onChange, onRemove, dragProps }: StepRowProps) {
  return (
    <li draggable {...dragProps}>
      <strong>{step.id}</strong> ({step.kind}){" "}
      <label>
        Retry attempts
        <input
          type="number"
          value={step.max_attempts ?? ""}
          onChange={(e) => onChange(withPolicy(step, "max_attempts", e.target.value))}
        />
      </label>{" "}
      <label>
        Review rounds
        <input
          type="number"
          value={step.review_rounds ?? ""}
          onChange={(e) => onChange(withPolicy(step, "review_rounds", e.target.value))}
        />
      </label>{" "}
      <button type="button" onClick={onRemove}>
        Remove
      </button>
    </li>
  );
}

function useRejections(workflow: Workflow, fail: (e: unknown) => void) {
  // null while the API is still checking the latest edit.
  const [rejections, setRejections] = useState<Rejection[] | null>(null);
  useEffect(() => {
    let current = true;
    setRejections(null);
    validateWorkflow(workflow)
      .then((r) => current && setRejections(r))
      .catch((e: unknown) => current && fail(e));
    return () => {
      current = false;
    };
    // Re-check on each edit; `fail` is a stable setter wrapper.
  }, [workflow]);
  return rejections;
}

export function Builder() {
  const [steps, setSteps] = useState<WorkflowStep[]>([]);
  const [name, setName] = useState("");
  const [versions, setVersions] = useState<number[]>([]);
  const [dragging, setDragging] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fail = (e: unknown) => setError(messageOf(e));
  const workflow = useMemo(() => toWorkflow(steps), [steps]);
  const rejections = useRejections(workflow, fail);
  const validName = NAME_PATTERN.test(name);

  useEffect(() => {
    if (!validName) return setVersions([]);
    listVersions(name).then(setVersions).catch(fail);
  }, [name, validName]);

  function add(kind: StepKind) {
    const extra = kind === "wait" ? { duration_seconds: DEFAULT_WAIT_SECONDS } : {};
    setSteps((current) => [...current, { id: freshId(current, kind), kind, ...extra }]);
  }

  async function save() {
    setError(null);
    try {
      await saveWorkflow(name, workflow);
      setVersions(await listVersions(name));
    } catch (e) {
      fail(e);
    }
  }

  const canSave = validName && rejections?.length === 0;
  return (
    <section>
      <h1>Workflow builder</h1>
      <button type="button" onClick={() => setSteps(TEMPLATE)}>
        Use template: {TEMPLATE_NAME}
      </button>
      <ol aria-label="Workflow steps">
        {steps.map((step, i) => (
          <StepRow
            key={step.id}
            step={step}
            onChange={(next) => setSteps(steps.map((s, j) => (j === i ? next : s)))}
            onRemove={() => setSteps(steps.filter((_, j) => j !== i))}
            dragProps={{
              onDragStart: () => setDragging(i),
              onDragOver: (e) => e.preventDefault(),
              onDrop: () => {
                if (dragging !== null) setSteps(moveStep(steps, dragging, i));
                setDragging(null);
              },
            }}
          />
        ))}
      </ol>
      <button type="button" onClick={() => add("agent")}>
        Add agent step
      </button>{" "}
      <button type="button" onClick={() => add("render")}>
        Add render step
      </button>{" "}
      <button type="button" onClick={() => add("approval")}>
        Add approval gate
      </button>{" "}
      <button type="button" onClick={() => add("publish")}>
        Add publish step
      </button>{" "}
      <button type="button" onClick={() => add("wait")}>
        Add wait step
      </button>
      {(rejections ?? []).length > 0 && (
        <div role="alert">
          {rejections?.map((r) => (
            <p key={r.message}>{r.message}</p>
          ))}
        </div>
      )}
      {error && <p role="alert">{error}</p>}
      <label>
        Workflow name
        <input value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <button type="button" disabled={!canSave} onClick={() => void save()}>
        Save version
      </button>
      <ul aria-label="Saved versions">
        {versions.map((v) => (
          <li key={v}>Version {v}</li>
        ))}
      </ul>
    </section>
  );
}
