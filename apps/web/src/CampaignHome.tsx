import type { ReactNode } from "react";
import type { Campaign, Me } from "./api";
import { campaignTitle, dollarsText, statusLabel } from "./labels";
import { campaignPath, NEW_CAMPAIGN_PATH } from "./route";
import { Card, EmptyBlock, LoadingBlock, StatusBadge, STATUS_TONES } from "./ui";

/** A link to a path inside the app: a real href, so it opens in a new tab and can be shared. */
export function NavLink({ path, go, className, children }: NavLinkProps) {
  return (
    <a
      href={path}
      className={className}
      onClick={(e) => {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
        e.preventDefault();
        go(path);
      }}
    >
      {children}
    </a>
  );
}

interface NavLinkProps {
  path: string;
  go: (path: string) => void;
  className?: string;
  children: ReactNode;
}

/** Owners run campaigns, so only they see the way to start one. The API enforces the same. */
export const canCreate = (me: Me): boolean => me.roles.includes("owner");

function CampaignCard({ me, campaign, go }: { me: Me; campaign: Campaign; go: (path: string) => void }) {
  return (
    <li className="card-item">
      <Card>
        <h3 className="card-title">
          <NavLink path={campaignPath(campaign.id)} go={go}>
            {campaignTitle(campaign)}
          </NavLink>
        </h3>
        <p>
          <span data-testid="card-status">
            <StatusBadge tone={STATUS_TONES[campaign.status]}>{statusLabel(campaign.status)}</StatusBadge>
          </span>
        </p>
        <dl className="card-facts">
          <dt>Owner</dt>
          {/* The API names the creator by an opaque id, so the card says only whether it is you. */}
          <dd data-testid="card-owner">{campaign.created_by === me.subject ? "You" : "A teammate"}</dd>
          <dt>Started</dt>
          <dd data-testid="card-started">
            <time dateTime={campaign.created_at}>{new Date(campaign.created_at).toLocaleString()}</time>
          </dd>
          <dt>Cost</dt>
          <dd data-testid="card-cost">{dollarsText(campaign.cost.cost_usd)}</dd>
        </dl>
      </Card>
    </li>
  );
}

interface CampaignHomeProps {
  me: Me;
  campaigns: Campaign[] | null;
  go: (path: string) => void;
}

export function CampaignHome({ me, campaigns, go }: CampaignHomeProps) {
  return (
    <section>
      <div className="page-head">
        <h1>Campaigns</h1>
        {canCreate(me) && (
          <NavLink path={NEW_CAMPAIGN_PATH} go={go} className="btn btn-primary">
            New campaign
          </NavLink>
        )}
      </div>
      {campaigns === null ? (
        <LoadingBlock>Loading your campaigns…</LoadingBlock>
      ) : campaigns.length === 0 ? (
        <EmptyBlock>
          No campaigns yet.{" "}
          {canCreate(me) ? (
            <NavLink path={NEW_CAMPAIGN_PATH} go={go} className="btn btn-primary">
              Start your first campaign
            </NavLink>
          ) : (
            "An owner on your team can start one."
          )}
        </EmptyBlock>
      ) : (
        <ul aria-label="Campaigns" className="card-list">
          {campaigns.map((c) => (
            <CampaignCard key={c.id} me={me} campaign={c} go={go} />
          ))}
        </ul>
      )}
    </section>
  );
}
