import { useEffect, useState } from "react";
import { SignedOutError } from "./api";
import { deleteLearning, listLearnings, type Learning } from "./learningsApi";
import { messageOf } from "./messages";
import { Card, EmptyBlock, ErrorBlock, LoadingBlock } from "./ui";

interface LearningsProps {
  canDelete: boolean;
  onOpenCampaign: (id: string) => void;
  onSignOut: () => void;
}

interface LearningItemProps {
  learning: Learning;
  canDelete: boolean;
  onOpenCampaign: (id: string) => void;
  onDelete: (id: string) => void;
}

/** The engine words the reason "Variant A won ..."; the app says "Version". */
const whyText = (reason: string): string => reason.replace(/^Variant /, "Version ");

/** The engine keeps a learning as its winning lines, one per line: the first is the title. */
const linesOf = (text: string): string[] => text.split("\n").filter((line) => line.trim() !== "");

function LearningItem({ learning, canDelete, onOpenCampaign, onDelete }: LearningItemProps) {
  const [title = "", ...details] = linesOf(learning.text);
  return (
    <li className="learning-item">
      <Card>
      <p className="learning-text" data-testid="learning-text">{title}</p>
      {details.map((line, index) => (
        <p key={`${index}-${line}`} className="learning-detail" data-testid="learning-detail">{line}</p>
      ))}
      <p className="learning-reason" data-testid="learning-reason">{whyText(learning.reason)}</p>
      <p>
        From campaign:{" "}
        <button type="button" onClick={() => onOpenCampaign(learning.campaign_id)}>
          {learning.campaign_title}
        </button>
      </p>
      {canDelete && (
        <button type="button" onClick={() => onDelete(learning.id)}>
          Delete
        </button>
      )}
      </Card>
    </li>
  );
}

function LearningsState({ error, learnings }: { error: string | null; learnings: Learning[] | null }) {
  if (error) return <ErrorBlock>{error}</ErrorBlock>;
  if (learnings === null) return <LoadingBlock>Loading learnings…</LoadingBlock>;
  if (learnings.length > 0) return null;
  return <EmptyBlock>No learnings yet. They appear once a campaign's A/B test picks a winner.</EmptyBlock>;
}

/** What the agents read before they write: each learning and the campaign it came from. */
export function Learnings({ canDelete, onOpenCampaign, onSignOut }: LearningsProps) {
  const [learnings, setLearnings] = useState<Learning[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  function fail(e: unknown) {
    if (e instanceof SignedOutError) onSignOut();
    else setError(messageOf(e));
  }

  async function load() {
    try {
      setLearnings(await listLearnings());
    } catch (e) {
      fail(e);
    }
  }

  async function remove(id: string) {
    try {
      await deleteLearning(id);
      await load();
    } catch (e) {
      fail(e);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  return (
    <section>
      <h2>Learnings</h2>
      <LearningsState error={error} learnings={learnings} />
      <ul className="learning-list" aria-label="Learnings">
        {(learnings ?? []).map((l) => (
          <LearningItem
            key={l.id}
            learning={l}
            canDelete={canDelete}
            onOpenCampaign={onOpenCampaign}
            onDelete={(id) => void remove(id)}
          />
        ))}
      </ul>
    </section>
  );
}
