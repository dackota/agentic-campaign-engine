import { useEffect, useState } from "react";
import { MAX_SCORE, SignedOutError } from "./api";
import { getDashboard, type Dashboard as DashboardData, type DashboardRow } from "./dashboardApi";
import { messageOf } from "./messages";

const COST_DECIMALS = 4;
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

/** A bar as wide as `value` is of `max`; the trend reads left to right as oldest to newest. */
function Bar({ value, max }: { value: number | null; max: number }) {
  const width = value === null || max === 0 ? 0 : Math.round((value / max) * PERCENT);
  return (
    <span
      aria-hidden="true"
      style={{ display: "inline-block", height: 8, width: `${width}px`, background: "#468" }}
    />
  );
}

function Trend({ rows }: { rows: DashboardRow[] }) {
  return (
    <section aria-label="Trend across campaigns">
      <h2>Trend</h2>
      <ol data-testid="dashboard-trend">
        {rows.map((r) => (
          <li key={r.id}>
            {r.title}: quality {quality(r.quality_score)} <Bar value={r.quality_score} max={MAX_SCORE} />
            , click rate {percent(r.click_rate)} <Bar value={r.click_rate} max={1} />
          </li>
        ))}
      </ol>
    </section>
  );
}

/** How the team's campaigns are doing. Read-only: it has no controls. */
export function Dashboard({ onSignOut }: { onSignOut: () => void }) {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getDashboard()
      .then(setData)
      .catch((e: unknown) => (e instanceof SignedOutError ? onSignOut() : setError(messageOf(e))));
  }, []);

  if (error) return <p role="alert">{error}</p>;
  if (!data) return <section aria-busy="true" />;
  const { totals } = data;
  return (
    <section data-testid="dashboard">
      <h1>Team dashboard</h1>
      <p>
        Runs: <span data-testid="dashboard-runs">{totals.runs}</span>, cost:{" "}
        <span data-testid="dashboard-total-cost">{dollars(totals.cost_usd)}</span>, quality:{" "}
        <span data-testid="dashboard-total-quality">{quality(totals.quality_score)}</span>, click rate:{" "}
        <span data-testid="dashboard-total-click-rate">{percent(totals.click_rate)}</span>
      </p>
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
              <td data-testid="dashboard-status">{STATUS_LABELS[r.status] ?? r.status}</td>
              <td data-testid="dashboard-cost">{dollars(r.cost_usd)}</td>
              <td data-testid="dashboard-quality">{quality(r.quality_score)}</td>
              <td data-testid="dashboard-click-rate">{percent(r.click_rate)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <Trend rows={data.campaigns} />
    </section>
  );
}
