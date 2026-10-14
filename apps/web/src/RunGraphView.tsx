import type { CSSProperties } from "react";
import { stepLabel, stepStatusLabel } from "./labels";
import { StatusBadge, type Tone } from "./ui";
import { graphLayout, summarizeSteps, type GraphEvent, type StepSummary } from "./runGraph";
import type { WorkflowEdge, WorkflowStep } from "./workflow.gen";

const NODE_WIDTH = 180;
const NODE_HEIGHT = 100;
const GAP_X = 56;
const GAP_Y = 16;
const PENDING = "pending";
const STATUS_TONES: Record<string, Tone> = { started: "info", succeeded: "ok", failed: "bad", pending: "warn" };

interface Position {
  x: number;
  y: number;
}

function positions(levels: string[][]): Map<string, Position> {
  const found = new Map<string, Position>();
  levels.forEach((level, column) =>
    level.forEach((id, row) =>
      found.set(id, { x: column * (NODE_WIDTH + GAP_X), y: row * (NODE_HEIGHT + GAP_Y) }),
    ),
  );
  return found;
}

/** The graph is as wide as its steps need, or the box it sits in when that is narrower: the
 * steps and their edges scale with the box, so no step hides behind a sideways scroll. */
function graphStyle(width: number, height: number): CSSProperties {
  return { maxWidth: width, height, "--node-w": NODE_WIDTH, "--graph-w": width } as CSSProperties;
}

interface RunGraphProps {
  dag: WorkflowStep[];
  edges: WorkflowEdge[];
  showDetails: boolean;
  events: GraphEvent[];
}

function Edges({ edges, at }: { edges: WorkflowEdge[]; at: Map<string, Position> }) {
  return edges.map((edge) => {
    const from = at.get(edge.from);
    const to = at.get(edge.to);
    if (!from || !to) return null;
    const [x1, y1] = [from.x + NODE_WIDTH, from.y + NODE_HEIGHT / 2];
    const [x2, y2] = [to.x, to.y + NODE_HEIGHT / 2];
    return (
      <line
        key={`${edge.from}-${edge.to}`}
        data-edge={`${edge.from}->${edge.to}`}
        x1={x1}
        y1={y1}
        x2={x2}
        y2={y2}
        className="run-edge"
      />
    );
  });
}

interface StepNodeProps {
  step: WorkflowStep;
  place: Position;
  /** The graph's natural width, so the step's left edge can be a share of the box. */
  graphWidth: number;
  info?: StepSummary;
  showDetails: boolean;
}

function StepNode({ step, place, graphWidth, info, showDetails }: StepNodeProps) {
  const status = info?.status ?? PENDING;
  return (
    <li
      className={`run-step run-step-${status}`}
      data-testid={`step-${step.id}`}
      data-status={status}
      style={{ left: `${(place.x / graphWidth) * 100}%`, top: place.y }}
    >
      <strong>{stepLabel(step.id)}</strong>
      <div>
        <StatusBadge tone={STATUS_TONES[status] ?? "info"}>{stepStatusLabel(status)}</StatusBadge>
      </div>
      {info && info.retries > 0 && <div>{`${info.retries} ${info.retries === 1 ? "retry" : "retries"}`}</div>}
      {showDetails && info && info.tokens > 0 && <div>{`${info.tokens} tokens`}</div>}
      {showDetails && info && info.alongside.length > 0 && <div>{`alongside ${info.alongside.join(", ")}`}</div>}
      {showDetails && <div>{`id ${step.id}`}</div>}
    </li>
  );
}

/** The workflow drawn as a graph: steps that can run together share a column, each step
 * shows its live status, retries, tokens, and which steps it ran alongside. */
export function RunGraph({ dag, edges, events, showDetails }: RunGraphProps) {
  const levels = graphLayout(dag, edges);
  const at = positions(levels);
  const summary = summarizeSteps(events);
  const width = levels.length * (NODE_WIDTH + GAP_X) - GAP_X;
  const height = Math.max(...levels.map((l) => l.length), 1) * (NODE_HEIGHT + GAP_Y) - GAP_Y;
  return (
    <div className="run-graph-scroll">
      <div data-testid="run-graph" className="run-graph" style={graphStyle(width, height)}>
        <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="run-edges" aria-hidden="true">
          <Edges edges={edges} at={at} />
        </svg>
        <ul aria-label="Run steps" className="run-steps">
          {dag.map((step) => (
            <StepNode key={step.id} step={step} place={at.get(step.id) ?? { x: 0, y: 0 }} graphWidth={width} info={summary[step.id]} showDetails={showDetails} />
          ))}
        </ul>
      </div>
    </div>
  );
}
