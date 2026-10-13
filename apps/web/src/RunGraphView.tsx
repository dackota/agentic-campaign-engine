import { graphLayout, summarizeSteps, type GraphEvent, type StepSummary } from "./runGraph";
import type { WorkflowEdge, WorkflowStep } from "./workflow.gen";

const NODE_WIDTH = 180;
const NODE_HEIGHT = 84;
const GAP_X = 56;
const GAP_Y = 16;
const PENDING = "pending";

const STEP_LABELS: Record<string, string> = { email_draft: "Email draft" };

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

interface RunGraphProps {
  dag: WorkflowStep[];
  edges: WorkflowEdge[];
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
        stroke="#888"
        strokeWidth={2}
      />
    );
  });
}

function StepNode({ step, place, info }: { step: WorkflowStep; place: Position; info?: StepSummary }) {
  const status = info?.status ?? PENDING;
  return (
    <li
      data-testid={`step-${step.id}`}
      data-status={status}
      style={{
        position: "absolute",
        left: place.x,
        top: place.y,
        width: NODE_WIDTH,
        height: NODE_HEIGHT,
        boxSizing: "border-box",
        padding: 6,
        overflow: "hidden",
        fontSize: 13,
        border: `2px solid ${status === "started" ? "#2563eb" : status === "failed" ? "#dc2626" : "#999"}`,
        borderRadius: 6,
        background: "#fff",
      }}
    >
      <strong>{STEP_LABELS[step.id] ?? step.id}</strong>: {status}
      {info && info.retries > 0 && <div>{`${info.retries} ${info.retries === 1 ? "retry" : "retries"}`}</div>}
      {info && info.tokens > 0 && <div>{`${info.tokens} tokens`}</div>}
      {info && info.alongside.length > 0 && <div>{`alongside ${info.alongside.join(", ")}`}</div>}
    </li>
  );
}

/** The workflow drawn as a graph: steps that can run together share a column, each step
 * shows its live status, retries, tokens, and which steps it ran alongside. */
export function RunGraph({ dag, edges, events }: RunGraphProps) {
  const levels = graphLayout(dag, edges);
  const at = positions(levels);
  const summary = summarizeSteps(events);
  const width = levels.length * (NODE_WIDTH + GAP_X) - GAP_X;
  const height = Math.max(...levels.map((l) => l.length), 1) * (NODE_HEIGHT + GAP_Y) - GAP_Y;
  return (
    <div style={{ overflowX: "auto", maxWidth: "100%" }}>
      <div data-testid="run-graph" style={{ position: "relative", width, height, margin: "8px 0" }}>
        <svg width={width} height={height} style={{ position: "absolute", inset: 0 }} aria-hidden="true">
          <Edges edges={edges} at={at} />
        </svg>
        <ul aria-label="Run steps" style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {dag.map((step) => (
            <StepNode key={step.id} step={step} place={at.get(step.id) ?? { x: 0, y: 0 }} info={summary[step.id]} />
          ))}
        </ul>
      </div>
    </div>
  );
}
