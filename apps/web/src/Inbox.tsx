import { useEffect, useState } from "react";
import { MAX_SCORE, SignedOutError } from "./api";
import { assetPreviewSrc, decideAsset, listInbox, type Decision, type InboxAsset } from "./inboxApi";
import { messageOf } from "./messages";

const INBOX_POLL_MS = 1500;
const PREVIEW_HEIGHT_PX = 360;

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
    <iframe
      title={`Preview of ${asset.step}`}
      src={assetPreviewSrc(asset.preview_url)}
      sandbox=""
      style={{ width: "100%", height: PREVIEW_HEIGHT_PX, border: "1px solid #ccc" }}
    />
  ) : (
    <pre data-testid="asset-text">{JSON.stringify(asset.output, null, 2)}</pre>
  );
}

function ReviewerFlags({ flags }: { flags: InboxAsset["flags"] }) {
  return (
    <section aria-label="Reviewer flags" data-testid="asset-flags">
      {flags.length === 0 ? (
        <p>No flags from the brand reviewer.</p>
      ) : (
        <ul>
          {flags.map((f, i) => (
            <li key={i}>
              {f.check}: {f.detail}
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
      aria-label={`${asset.title}: ${asset.step}`}
      aria-current={isLinked ? "true" : undefined}
      data-testid="inbox-asset"
    >
      <h3>
        {asset.title} <small>({asset.step})</small>
      </h3>
      <AssetPreview asset={asset} />
      <JudgeScore asset={asset} />
      <ReviewerFlags flags={asset.flags} />
      <label>
        Comment
        <input value={comment} onChange={(e) => setComment(e.target.value)} />
      </label>{" "}
      <button type="button" disabled={isBusy} onClick={() => void decide("approve")}>
        Approve
      </button>{" "}
      <button type="button" disabled={isBusy || !comment.trim()} onClick={() => void decide("reject")}>
        Reject
      </button>
    </article>
  );
}

interface InboxProps {
  onSignOut: () => void;
  /** The campaign a Slack link opened, shown first. */
  linkedCampaign: string | null;
}

/** The approver's queue: every asset waiting for their team, decided one by one. */
export function Inbox({ onSignOut, linkedCampaign }: InboxProps) {
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

  async function decide(asset: InboxAsset, decision: Decision, comment: string) {
    setError(null);
    try {
      await decideAsset(asset, decision, comment);
      await refresh();
    } catch (e) {
      if (e instanceof SignedOutError) onSignOut();
      else setError(messageOf(e));
    }
  }

  const ordered = [...(assets ?? [])].sort(
    (a, b) => Number(b.campaign_id === linkedCampaign) - Number(a.campaign_id === linkedCampaign),
  );
  return (
    <section>
      <h2>Approval inbox</h2>
      {error && <p role="alert">{error}</p>}
      {assets !== null && assets.length === 0 && <p>Nothing is waiting for approval.</p>}
      {ordered.map((a) => (
        <AssetCard
          key={`${a.campaign_id}:${a.step}`}
          asset={a}
          isLinked={a.campaign_id === linkedCampaign}
          onDecide={decide}
        />
      ))}
    </section>
  );
}
