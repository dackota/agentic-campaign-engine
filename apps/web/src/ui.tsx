import type { ReactElement, ReactNode } from "react";
import type { CampaignStatus } from "./api";

export type Tone = "ok" | "warn" | "bad" | "info";
/** How a campaign's status looks on the run page and in the campaign list. */
export const STATUS_TONES: Record<CampaignStatus, Tone> = {
  drafting: "info",
  awaiting_approval: "warn",
  sending: "info",
  sent: "ok",
  failed: "bad",
  retrying: "warn",
  finished: "ok",
  budget_paused: "warn",
};

const ICONS: Record<Tone, string> = { ok: "✓", warn: "!", bad: "✕", info: "i" };

/** Status as color, icon, and word together, never color alone. */
export function StatusBadge({ tone, children }: { tone: Tone; children: ReactNode }): ReactElement {
  return (
    <span className={`badge badge-${tone}`}>
      <span aria-hidden="true">{ICONS[tone]}</span> {children}
    </span>
  );
}

export function Card({ children, label }: { children: ReactNode; label?: string }): ReactElement {
  return (
    <section className="card" aria-label={label}>
      {children}
    </section>
  );
}

export function EmptyBlock({ children }: { children: ReactNode }): ReactElement {
  return <p className="block block-empty">{children}</p>;
}

export function LoadingBlock({ children = "Loading…" }: { children?: ReactNode }): ReactElement {
  return (
    <p className="block block-loading" role="status">
      {children}
    </p>
  );
}

export function ErrorBlock({ children }: { children: ReactNode }): ReactElement {
  return (
    <p className="block block-error" role="alert">
      {children}
    </p>
  );
}
