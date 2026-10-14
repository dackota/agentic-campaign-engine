import type { ReactElement, ReactNode } from "react";

export type Tone = "ok" | "warn" | "bad" | "info";
const ICONS: Record<Tone, string> = { ok: "✓", warn: "!", bad: "✕", info: "i" };

/** Status as color, icon, and word together, never color alone. */
export function StatusBadge({ tone, children }: { tone: Tone; children: ReactNode }): ReactElement {
  return (
    <span className={`badge badge-${tone}`}>
      <span aria-hidden="true">{ICONS[tone]}</span> {children}
    </span>
  );
}

export function Card({ children }: { children: ReactNode }): ReactElement {
  return <section className="card">{children}</section>;
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
