import type { ReactElement } from "react";
import type { Me } from "./api";

export type View = "campaigns" | "builder" | "inbox" | "learnings" | "dashboard";

export const PRODUCT_NAME = "Agentic Campaign Engine";

interface HeaderProps {
  me: Me;
  onSignOut: () => void;
}

/** Product name, team, and the user menu (a native disclosure, so the keyboard works). */
export function Header({ me, onSignOut }: HeaderProps): ReactElement {
  return (
    <header className="app-header">
      <span className="app-name">{PRODUCT_NAME}</span>
      <span className="app-team">
        Team: <span data-testid="team">{me.team ?? "No team"}</span>
      </span>
      <details className="user-menu">
        <summary data-testid="signed-in-as">{me.email}</summary>
        <div className="user-menu-panel">
          <button type="button" className="btn btn-secondary" onClick={onSignOut}>
            Sign out
          </button>
        </div>
      </details>
    </header>
  );
}

interface ViewNavProps {
  me: Me;
  view: View;
  onView: (view: View) => void;
}

export function ViewNav({ me, view, onView }: ViewNavProps): ReactElement {
  const items: [View, string][] = [
    ["campaigns", "Campaigns"],
    ["builder", "Workflow builder"],
    ["learnings", "Learnings"],
    ["dashboard", "Dashboard"],
  ];
  if (me.roles.includes("approver")) items.push(["inbox", "Inbox"]);
  return (
    <nav className="app-nav" aria-label="Main">
      {items.map(([id, label]) => (
        <button
          key={id}
          type="button"
          aria-current={id === view ? "page" : undefined}
          onClick={() => onView(id)}
        >
          {label}
        </button>
      ))}
    </nav>
  );
}
