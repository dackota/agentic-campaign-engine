import type { WorkflowEdge, WorkflowStep } from "./workflow.gen";

/** The part of a run event the graph reads. */
export interface GraphEvent {
  seq: number;
  step: string;
  status: string;
  tokens: number | null;
}

export interface StepSummary {
  status: string;
  /** Attempts after the first: a step that started twice retried once. */
  retries: number;
  tokens: number;
  /** The other steps whose runs overlapped this one's. */
  alongside: string[];
}

const STARTED = "started";
const ENDED = ["succeeded", "failed"];

/** Group step ids into levels by their longest path from a root, in declared order, so
 * steps that can run side by side share a level. */
export function graphLayout(steps: WorkflowStep[], edges: WorkflowEdge[]): string[][] {
  const depth = new Map<string, number>();
  const depthOf = (id: string, seen: Set<string>): number => {
    const known = depth.get(id);
    if (known !== undefined) return known;
    if (seen.has(id)) return 0;
    const parents = edges.filter((e) => e.to === id).map((e) => e.from);
    const value = parents.length === 0 ? 0 : 1 + Math.max(...parents.map((p) => depthOf(p, new Set([...seen, id]))));
    depth.set(id, value);
    return value;
  };
  const levels: string[][] = [];
  for (const { id } of steps) {
    const level = depthOf(id, new Set());
    (levels[level] ??= []).push(id);
  }
  return levels.filter((level) => level.length > 0);
}

interface Span {
  start: number;
  end: number;
}

/** What each step shows: latest status, retries, tokens, and the steps it ran alongside.
 * Overlap comes from event order, so it holds however fast the events arrived. */
export function summarizeSteps(events: GraphEvent[]): Record<string, StepSummary> {
  const spans = new Map<string, Span>();
  const summary: Record<string, StepSummary> = {};
  for (const e of [...events].sort((a, b) => a.seq - b.seq)) {
    const current = summary[e.step] ?? { status: e.status, retries: -1, tokens: 0, alongside: [] };
    const span = spans.get(e.step) ?? { start: e.seq, end: Infinity };
    if (e.status === STARTED) current.retries += 1;
    if (ENDED.includes(e.status)) span.end = e.seq;
    else span.end = Infinity;
    spans.set(e.step, span);
    summary[e.step] = { ...current, status: e.status, tokens: current.tokens + (e.tokens ?? 0) };
  }
  for (const [id, own] of Object.entries(summary)) {
    own.retries = Math.max(own.retries, 0);
    own.alongside = [...spans]
      .filter(([other, s]) => other !== id && s.start < spans.get(id)!.end && spans.get(id)!.start < s.end)
      .map(([other]) => other);
  }
  return summary;
}
