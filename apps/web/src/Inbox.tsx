import { useEffect, useState } from "react";
import { MAX_SCORE, SignedOutError } from "./api";
import { assetPreviewSrc, decideAsset, listInbox, type Decision, type InboxAsset } from "./inboxApi";
import { cleanAssets, groupByCampaign, type CampaignGroup } from "./inboxGroups";
import { flagLabel, stepLabel } from "./labels";
import { PreviewFrame } from "./PreviewFrame";
import { Card, EmptyBlock, ErrorBlock, LoadingBlock } from "./ui";
import { messageOf } from "./messages";

const INBOX_POLL_MS = 1500;

/** The inbox link a Slack message carries (`?inbox=<campaign id>`), kept across sign-in. */
const INBOX_LINK_KEY = "ace.inbox_link";

export function rememberInboxLink(): void {
  const id = new URLSearchParams(window.location.search).get("inbox");
  if (id) sessionStorage.setItem(INBOX_LINK_KEY, id);
}

/** The campaign a link asked for, once; null when the user came another way. */
export function takeInboxLink(): string | null {
  const id = sessionStorage.getItem(INBOX_LINK_KEY);
  sessionStorage.removeItem(INBOX_LINK_KEY);
  return id;
}

interface AssetCardProps {
  asset: InboxAsset;
  isLinked: boolean;
  onDecide: (asset: InboxAsset, decision: Decision, comment: string) => Promise<void>;
}

function AssetPreview({ asset }: { asset: InboxAsset }) {
  return asset.preview_url ? (
    <PreviewFrame title={`Preview of ${stepLabel(asset.step)}`} src={assetPreviewSrc(asset.preview_url)} />
  ) : (
    <pre data-testid="asset-text">{JSON.stringify(asset.output, null, 2)}</pre>
  );
}

function ReviewerFlags({ flags }: { flags: InboxAsset["flags"] }) {
  return (
    <section aria-label="Reviewer flags" data-testid="asset-flags" className={flags.length ? "flag-note" : undefined}>
      {flags.length === 0 ? (
        <p>No flags from the brand reviewer.</p>
      ) : (
        <ul>
          {flags.map((f, i) => (
            <li key={i}>
              <strong>{flagLabel(f.check)}:</strong> {f.detail}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function JudgeScore({ asset }: { asset: InboxAsset }) {
  if (asset.score === null) return null;
  return (
    <p aria-label="Judge score">
      Judge: <strong data-testid="asset-score">{`${asset.score}/${MAX_SCORE}`}</strong>{" "}
      <span data-testid="asset-score-reason">{asset.score_reason}</span>
    </p>
  );
}

function AssetCard({ asset, isLinked, onDecide }: AssetCardProps) {
  const [comment, setComment] = useState("");
  const [isBusy, setIsBusy] = useState(false);

  async function decide(decision: Decision) {
    setIsBusy(true);
    try {
      await onDecide(asset, decision, comment.trim());
    } finally {
      setIsBusy(false);
    }
  }

  return (
    <article
      aria-label={`${asset.title}: ${stepLabel(asset.step)}`}
      aria-current={isLinked ? "true" : undefined}
      data-testid="inbox-asset"
      className="inbox-asset"
    >
      <h4>
        {asset.title}: {stepLabel(asset.step)}
      </h4>
      <AssetPreview asset={asset} />
      <JudgeScore asset={asset} />
      <ReviewerFlags flags={asset.flags} />
      <div className="decision-row">
        <label>
          Comment
          <input value={comment} onChange={(e) => setComment(e.target.value)} />
        </label>
        <button type="button" className="btn-primary" disabled={isBusy} onClick={() => void decide("approve")}>
          Approve
        </button>
        <button type="button" className="btn-danger" disabled={isBusy || !comment.trim()} onClick={() => void decide("reject")}>
          Reject (comment needed)
        </button>
      </div>
    </article>
  );
}

interface CampaignSectionProps {
  group: CampaignGroup;
  isLinked: boolean;
  cleanCount: number;
  onDecide: AssetCardProps["onDecide"];
  onApproveAllClean: (campaignId: string) => Promise<void>;
}

function CampaignSection({ group, isLinked, cleanCount, onDecide, onApproveAllClean }: CampaignSectionProps) {
  const waiting = group.assets.length;
  return (
    <Card>
      <div role="region" aria-label={group.title} className="inbox-group">
        <div className="inbox-group-head">
          <h3>{group.title}</h3>
          <span data-testid="campaign-waiting">{`${waiting} ${waiting === 1 ? "asset" : "assets"} waiting`}</span>
          <button
            type="button"
            className="btn-secondary"
            disabled={cleanCount === 0}
            onClick={() => void onApproveAllClean(group.campaignId)}
          >
            {`Approve all with no flags (${cleanCount})`}
          </button>
        </div>
        {group.assets.map((a) => (
          <AssetCard key={a.step} asset={a} isLinked={isLinked} onDecide={onDecide} />
        ))}
      </div>
    </Card>
  );
}

interface InboxProps {
  onSignOut: () => void;
  /** The campaign a Slack link opened, shown first. */
  linkedCampaign: string | null;
}

/** The queue, reloaded on a timer, and the decisions that change it. */
function useInbox(onSignOut: () => void) {
  const [assets, setAssets] = useState<InboxAsset[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      setAssets(await listInbox());
    } catch (e) {
      if (e instanceof SignedOutError) onSignOut();
      else setError(messageOf(e));
    }
  }

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), INBOX_POLL_MS);
    return () => clearInterval(timer);
    // The inbox reloads itself on a timer for as long as it is on screen.
  }, []);

  async function act(work: () => Promise<void>) {
    setError(null);
    try {
      await work();
      await refresh();
    } catch (e) {
      if (e instanceof SignedOutError) onSignOut();
      else setError(messageOf(e));
    }
  }

  const decide = (asset: InboxAsset, decision: Decision, comment: string) =>
    act(() => decideAsset(asset, decision, comment));
  const approveAllClean = (campaignId: string) =>
    act(async () => {
      for (const a of cleanAssets(assets ?? [], campaignId)) await decideAsset(a, "approve", "");
    });

  return { assets, error, decide, approveAllClean };
}

/** The approver's queue: every asset waiting for their team, grouped by campaign. */
export function Inbox({ onSignOut, linkedCampaign }: InboxProps) {
  const { assets, error, decide, approveAllClean } = useInbox(onSignOut);
  const groups = groupByCampaign(assets ?? [], linkedCampaign);
  return (
    <section>
      <h2>Approval inbox</h2>
      {error && <ErrorBlock>{error}</ErrorBlock>}
      {assets === null && !error && <LoadingBlock>Loading your inbox…</LoadingBlock>}
      {assets !== null && assets.length === 0 && <EmptyBlock>Nothing is waiting for approval.</EmptyBlock>}
      {groups.map((g) => (
        <CampaignSection
          key={g.campaignId}
          group={g}
          isLinked={g.campaignId === linkedCampaign}
          cleanCount={cleanAssets(g.assets, g.campaignId).length}
          onDecide={decide}
          onApproveAllClean={approveAllClean}
        />
      ))}
    </section>
  );
}
