import { useEffect, useMemo, useRef, useState } from "react";
import { listVersions, saveWorkflow, validateWorkflow, type Rejection } from "./builderApi";
import { messageOf } from "./messages";
import { kindDescription, kindLabel, stepLabel } from "./labels";
import { problemsOf, type Problem } from "./builderMessages";
import { Card, EmptyBlock, ErrorBlock, LoadingBlock } from "./ui";
import { StepKindValues, type StepKind, type Workflow, type WorkflowStep } from "./workflow.gen";

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
  problems: Problem[];
  onChange: (step: WorkflowStep) => void;
  onRemove: () => void;
  onKeyMove: (delta: number) => void;
  dragProps: React.HTMLAttributes<HTMLLIElement>;
}

function StepRow({ step, problems, onChange, onRemove, onKeyMove, dragProps }: StepRowProps) {
  const name = stepLabel(step.id);
  const kind = kindLabel(step.kind);
  return (
    <li className="step-row" draggable {...dragProps}>
      <button
        type="button"
        className="drag-handle"
        data-step-id={step.id}
        aria-label={`Move ${name}`}
        title="Drag, or press the up and down arrow keys, to move this step"
        onKeyDown={(e) => {
          if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
          e.preventDefault();
          onKeyMove(e.key === "ArrowUp" ? -1 : 1);
        }}
      >
        <span aria-hidden="true">⠿</span>
      </button>
      <strong>{name}</strong>
      {kind !== name && <> ({kind})</>}{" "}
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
      {problems.map((p) => (
        <ErrorBlock key={p.text}>{p.text}</ErrorBlock>
      ))}
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
    // Re-check on each edit. `fail` is new each render but only wraps the stable setError.
  }, [workflow]);
  return rejections;
}

function Palette({ onAdd }: { onAdd: (kind: StepKind) => void }) {
  return (
    <ul aria-label="Step palette" className="palette">
      {StepKindValues.map((kind) => (
        <li key={kind}>
          <button type="button" onClick={() => onAdd(kind)}>
            Add {kindLabel(kind)}
          </button>
          <p>{kindDescription(kind)}</p>
        </li>
      ))}
    </ul>
  );
}

function ProblemList({ problems }: { problems: Problem[] }) {
  return (
    <>
      {problems.map((p) => (
        <ErrorBlock key={p.text}>{p.text}</ErrorBlock>
      ))}
    </>
  );
}

function Gallery({ onPick }: { onPick: (steps: WorkflowStep[]) => void }) {
  return (
    <>
      <p>Start from a template, or build your own.</p>
      <Card>
        <h2>{TEMPLATE_NAME}</h2>
        <p>An email draft, a person's approval, then publish.</p>
        <button type="button" className="btn-primary" onClick={() => onPick(TEMPLATE)}>
          Use template: {TEMPLATE_NAME}
        </button>
      </Card>
      <Card>
        <h2>Blank workflow</h2>
        <p>An empty canvas: add each step yourself.</p>
        <button type="button" onClick={() => onPick([])}>
          Start a blank workflow
        </button>
      </Card>
    </>
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
    let isCurrent = true;
    listVersions(name)
      .then((v) => isCurrent && setVersions(v))
      .catch((e: unknown) => isCurrent && fail(e));
    return () => {
      isCurrent = false;
    };
  }, [name, isValidName]);
  return [versions, setVersions] as const;
}

interface StepListProps {
  steps: WorkflowStep[];
  problems: Problem[];
  onSteps: (steps: WorkflowStep[]) => void;
}

function StepList({ steps, problems, onSteps }: StepListProps): React.JSX.Element {
  const [dragging, setDragging] = useState<number | null>(null);
  const listRef = useRef<HTMLOListElement>(null);
  const [focusId, setFocusId] = useState<string | null>(null);
  // Keep keyboard focus on the handle of the step that just moved.
  useEffect(() => {
    if (focusId === null) return;
    listRef.current?.querySelector<HTMLElement>(`[data-step-id="${CSS.escape(focusId)}"]`)?.focus();
    setFocusId(null);
  }, [focusId]);
  const keyMove = (i: number, delta: number) => {
    const to = i + delta;
    if (to < 0 || to >= steps.length) return;
    onSteps(moveStep(steps, i, to));
    setFocusId(steps[i]!.id);
  };
  return (
    <ol aria-label="Workflow steps" className="step-list" ref={listRef}>
      {steps.map((step, i) => (
        <StepRow
          key={step.id}
          step={step}
          problems={problems.filter((p) => p.stepId === step.id)}
          onChange={(next) => onSteps(steps.map((s, j) => (j === i ? next : s)))}
          onRemove={() => onSteps(steps.filter((_, j) => j !== i))}
          onKeyMove={(delta) => keyMove(i, delta)}
          dragProps={{
            onDragStart: () => setDragging(i),
            onDragOver: (e) => e.preventDefault(),
            onDrop: () => {
              if (dragging !== null) onSteps(moveStep(steps, dragging, i));
              setDragging(null);
            },
          }}
        />
      ))}
    </ol>
  );
}

export function Builder(): React.JSX.Element {
  // null: the template gallery, before the user has picked anything.
  const [picked, setPicked] = useState<WorkflowStep[] | null>(null);
  if (picked === null) {
    return (
      <section>
        <h1>Workflow builder</h1>
        <Gallery onPick={setPicked} />
      </section>
    );
  }
  return <Editor initial={picked} />;
}

function Editor({ initial }: { initial: WorkflowStep[] }) {
  const [steps, setSteps] = useState<WorkflowStep[]>(initial);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const fail = (e: unknown) => setError(messageOf(e));
  const workflow = useMemo(() => toWorkflow(steps), [steps]);
  const rejections = useRejections(workflow, fail);
  const problems = problemsOf(steps, rejections ?? []);
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
      <h2>Steps</h2>
      {steps.length === 0 && <EmptyBlock>No steps yet. Add one from the palette below.</EmptyBlock>}
      <StepList steps={steps} problems={problems} onSteps={setSteps} />
      <ProblemList problems={problems.filter((p) => p.stepId === null)} />
      {rejections === null && <LoadingBlock>Checking your workflow…</LoadingBlock>}
      <h2>Step palette</h2>
      <Palette onAdd={add} />
      {error && <ErrorBlock>{error}</ErrorBlock>}
      <VersionPanel
        name={name}
        versions={versions}
        canSave={isValidName && rejections !== null && problems.length === 0}
        onName={setName}
        onSave={() => void save()}
      />
    </section>
  );
}
