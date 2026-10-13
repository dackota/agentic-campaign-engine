import { fetchJson } from "./api";

export interface DashboardRow {
  id: string;
  title: string;
  status: string;
  created_at: string;
  cost_usd: number;
  quality_score: number | null;
  click_rate: number | null;
}

export interface DashboardTotals {
  runs: number;
  cost_usd: number;
  quality_score: number | null;
  click_rate: number | null;
}

/** The team's campaigns, oldest first, with totals. */
export interface Dashboard {
  campaigns: DashboardRow[];
  totals: DashboardTotals;
}

const isNumberOrNull = (v: unknown): boolean => v === null || typeof v === "number";

function isRow(value: unknown): value is DashboardRow {
  if (typeof value !== "object" || value === null) return false;
  const r = value as Record<string, unknown>;
  return (
    typeof r.id === "string" &&
    typeof r.title === "string" &&
    typeof r.status === "string" &&
    typeof r.created_at === "string" &&
    typeof r.cost_usd === "number" &&
    isNumberOrNull(r.quality_score) &&
    isNumberOrNull(r.click_rate)
  );
}

function isTotals(value: unknown): value is DashboardTotals {
  if (typeof value !== "object" || value === null) return false;
  const t = value as Record<string, unknown>;
  return (
    typeof t.runs === "number" &&
    typeof t.cost_usd === "number" &&
    isNumberOrNull(t.quality_score) &&
    isNumberOrNull(t.click_rate)
  );
}

export async function getDashboard(): Promise<Dashboard> {
  const body = await fetchJson("/dashboard");
  const d = body as Record<string, unknown> | null;
  if (!d || !Array.isArray(d.campaigns) || !d.campaigns.every(isRow) || !isTotals(d.totals)) {
    throw new Error("the API returned an unexpected dashboard");
  }
  return { campaigns: d.campaigns, totals: d.totals };
}
