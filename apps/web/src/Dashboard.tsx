import { useEffect, useState, type ReactElement } from "react";
import { MAX_SCORE, SignedOutError } from "./api";
import { getDashboard, type Dashboard as DashboardData, type DashboardTotals, type DashboardRow } from "./dashboardApi";
import { messageOf } from "./messages";
import { Card, ErrorBlock, LoadingBlock, StatusBadge, type Tone } from "./ui";

const COST_DECIMALS = 2;
const PERCENT = 100;
const STATUS_LABELS: Record<string, string> = {
  drafting: "Drafting",
  awaiting_approval: "Waiting for approval",
  sending: "Sending",
  sent: "Sent",
  failed: "Failed",
  retrying: "Retrying",
  finished: "Finished",
  budget_paused: "Paused at budget",
};
const NOT_YET = "n/a";

const dollars = (usd: number): string => `$${usd.toFixed(COST_DECIMALS)}`;
const quality = (score: number | null): string =>
  score === null ? NOT_YET : `${score.toFixed(1)}/${MAX_SCORE}`;
const percent = (rate: number | null): string =>
  rate === null ? NOT_YET : `${Math.round(rate * PERCENT)}%`;

const CHART_W = 600;
const CHART_H = 240;
const PAD_L = 50;
const PAD_R = 50;
const PAD_T = 16;
const PAD_B = 50;
const PLOT_W = CHART_W - PAD_L - PAD_R;
const PLOT_H = CHART_H - PAD_T - PAD_B;

const statusTone = (status: string): Tone =>
  status === "failed" ? "bad" : status === "sent" || status === "finished" ? "ok" : status === "budget_paused" ? "warn" : "info";

interface TrendProps {
  rows: DashboardRow[];
}

/** Click rate (left axis, percent) and quality (right axis, out of 5) per campaign, oldest first. */
function Trend({ rows }: TrendProps) {
  const x = (i: number): number => PAD_L + (rows.length < 2 ? PLOT_W / 2 : (i / (rows.length - 1)) * PLOT_W);
  const y = (fraction: number): number => PAD_T + (1 - fraction) * PLOT_H;
  const line = (pick: (r: DashboardRow) => number | null): string =>
    rows.flatMap((r, i) => { const v = pick(r); return v === null ? [] : [`${x(i)},${y(v)}`]; }).join(" ");
  const summary = `Click rate and quality for ${rows.length} campaigns, oldest to newest.`;
  return (
    <Card>
      <h2>Trend</h2>
      <svg
        className="trend-chart"
        viewBox={`0 0 ${CHART_W} ${CHART_H}`}
        role="img"
        aria-label={summary}
        data-testid="dashboard-trend-chart"
      >
        <line className="trend-axis" x1={PAD_L} y1={y(0)} x2={PAD_L + PLOT_W} y2={y(0)} />
        <line className="trend-axis" x1={PAD_L} y1={y(0)} x2={PAD_L} y2={y(1)} />
        <line className="trend-axis" x1={PAD_L + PLOT_W} y1={y(0)} x2={PAD_L + PLOT_W} y2={y(1)} />
        <polyline className="trend-click" points={line((r) => r.click_rate)} />
        <polyline className="trend-quality" points={line((r) => (r.quality_score === null ? null : r.quality_score / MAX_SCORE))} />
        <text className="trend-label trend-click-text" x={PAD_L - 6} y={y(1)} textAnchor="end">100%</text>
        <text className="trend-label trend-click-text" x={PAD_L - 6} y={y(0)} textAnchor="end">0%</text>
        <text className="trend-label trend-quality-text" x={PAD_L + PLOT_W + 6} y={y(1)}>{MAX_SCORE}</text>
        <text className="trend-label trend-quality-text" x={PAD_L + PLOT_W + 6} y={y(0)}>0</text>
        <text className="trend-label trend-click-text" x={12} y={PAD_T + PLOT_H / 2} transform={`rotate(-90 12 ${PAD_T + PLOT_H / 2})`} textAnchor="middle">Click rate</text>
        <text className="trend-label trend-quality-text" x={CHART_W - 12} y={PAD_T + PLOT_H / 2} transform={`rotate(90 ${CHART_W - 12} ${PAD_T + PLOT_H / 2})`} textAnchor="middle">Quality</text>
        <text className="trend-label" x={PAD_L + PLOT_W / 2} y={CHART_H - 8} textAnchor="middle">Campaign</text>
        {rows.map((r, i) => (
          <text key={r.id} className="trend-label" x={x(i)} y={y(0) + 16} textAnchor="middle">{i + 1}</text>
        ))}
      </svg>
      <ol data-testid="dashboard-trend">
        {rows.map((r) => (
          <li key={r.id}>
            {`${r.title}: quality ${quality(r.quality_score)}, click rate ${percent(r.click_rate)}`}
          </li>
        ))}
      </ol>
    </Card>
  );
}

function Tile({ label, testId, children }: { label: string; testId: string; children: string | number }): ReactElement {
  return (
    <li className="tile">
      <span className="tile-label">{label}</span>
      <span className="tile-value" data-testid={testId}>{children}</span>
    </li>
  );
}

function Totals({ totals }: { totals: DashboardTotals }): ReactElement {
  return (
    <ul className="tiles" data-testid="dashboard-tiles" aria-label="Team totals">
      <Tile label="Campaigns run" testId="dashboard-runs">{totals.runs}</Tile>
      <Tile label="Average quality" testId="dashboard-total-quality">{quality(totals.quality_score)}</Tile>
      <Tile label="Average click rate" testId="dashboard-total-click-rate">{percent(totals.click_rate)}</Tile>
      <Tile label="Total cost" testId="dashboard-total-cost">{dollars(totals.cost_usd)}</Tile>
    </ul>
  );
}

/** How the team's campaigns are doing. Read-only: it has no controls. */
interface DashboardProps {
  onSignOut: () => void;
}

export function Dashboard({ onSignOut }: DashboardProps): ReactElement {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getDashboard()
      .then(setData)
      .catch((e: unknown) => {
        if (e instanceof SignedOutError) onSignOut();
        else setError(messageOf(e));
      });
  }, []);

  if (error) return <ErrorBlock>{error}</ErrorBlock>;
  if (!data) return <LoadingBlock>Loading the dashboard…</LoadingBlock>;
  const { totals } = data;
  return (
    <section data-testid="dashboard">
      <h1>Team dashboard</h1>
      <Totals totals={totals} />
      <Trend rows={data.campaigns} />
      <table>
        <thead>
          <tr>
            <th>Campaign</th>
            <th>Status</th>
            <th>Cost</th>
            <th>Quality</th>
            <th>Click rate</th>
          </tr>
        </thead>
        <tbody>
          {data.campaigns.map((r) => (
            <tr key={r.id} data-testid={`dashboard-row-${r.title}`}>
              <td>{r.title}</td>
              <td>
                <StatusBadge tone={statusTone(r.status)}>
                  <span data-testid="dashboard-status">{STATUS_LABELS[r.status] ?? r.status}</span>
                </StatusBadge>
              </td>
              <td data-testid="dashboard-cost">{dollars(r.cost_usd)}</td>
              <td data-testid="dashboard-quality">{quality(r.quality_score)}</td>
              <td data-testid="dashboard-click-rate">{percent(r.click_rate)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
