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
const FIRST_DUPLICATE_SUFFIX = 2;
// Must match NAME_PATTERN in apps/api/campaign_api/workflows.py.
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
  let n = FIRST_DUPLICATE_SUFFIX;
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
    let isCurrent = true;
    setRejections(null);
    validateWorkflow(workflow)
      .then((r) => isCurrent && setRejections(r))
      .catch((e: unknown) => isCurrent && fail(e));
    return () => {
      isCurrent = false;
    };
    // Re-check on each edit; `fail` is a stable setter wrapper.
  }, [workflow]);
  return rejections;
}

const ADDABLE: { kind: StepKind; label: string }[] = [
  { kind: "agent", label: "Add agent step" },
  { kind: "render", label: "Add render step" },
  { kind: "approval", label: "Add approval gate" },
  { kind: "publish", label: "Add publish step" },
  { kind: "wait", label: "Add wait step" },
];

function AddStepBar({ onAdd }: { onAdd: (kind: StepKind) => void }) {
  return (
    <>
      {ADDABLE.map(({ kind, label }) => (
        <button key={kind} type="button" onClick={() => onAdd(kind)}>
          {label}
        </button>
      ))}
    </>
  );
}

function RejectionAlert({ rejections }: { rejections: Rejection[] | null }) {
  if (!rejections || rejections.length === 0) return null;
  return (
    <div role="alert">
      {rejections.map((r) => (
        <p key={r.message}>{r.message}</p>
      ))}
    </div>
  );
}

interface VersionPanelProps {
  name: string;
  versions: number[];
  canSave: boolean;
  onName: (name: string) => void;
  onSave: () => void;
}

function VersionPanel({ name, versions, canSave, onName, onSave }: VersionPanelProps) {
  return (
    <>
      <label>
        Workflow name
        <input value={name} onChange={(e) => onName(e.target.value)} />
      </label>
      <button type="button" disabled={!canSave} onClick={onSave}>
        Save version
      </button>
      <ul aria-label="Saved versions">
        {versions.map((v) => (
          <li key={v}>Version {v}</li>
        ))}
      </ul>
    </>
  );
}

function useSavedVersions(name: string, isValidName: boolean, fail: (e: unknown) => void) {
  const [versions, setVersions] = useState<number[]>([]);
  useEffect(() => {
    if (!isValidName) return setVersions([]);
    listVersions(name).then(setVersions).catch(fail);
  }, [name, isValidName]);
  return [versions, setVersions] as const;
}

export function Builder(): React.JSX.Element {
  const [steps, setSteps] = useState<WorkflowStep[]>([]);
  const [name, setName] = useState("");
  const [dragging, setDragging] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fail = (e: unknown) => setError(messageOf(e));
  const workflow = useMemo(() => toWorkflow(steps), [steps]);
  const rejections = useRejections(workflow, fail);
  const isValidName = NAME_PATTERN.test(name);
  const [versions, setVersions] = useSavedVersions(name, isValidName, fail);

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
      <AddStepBar onAdd={add} />
      <RejectionAlert rejections={rejections} />
      {error && <p role="alert">{error}</p>}
      <VersionPanel
        name={name}
        versions={versions}
        canSave={isValidName && rejections?.length === 0}
        onName={setName}
        onSave={() => void save()}
      />
    </section>
  );
}
