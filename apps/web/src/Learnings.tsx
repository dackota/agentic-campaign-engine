import { useEffect, useState } from "react";
import { SignedOutError } from "./api";
import { deleteLearning, listLearnings, type Learning } from "./learningsApi";
import { messageOf } from "./messages";

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

function LearningItem({ learning, canDelete, onOpenCampaign, onDelete }: LearningItemProps) {
  return (
    <li>
      <pre data-testid="learning-text">{learning.text}</pre>
      <p data-testid="learning-reason">{learning.reason}</p>
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
    </li>
  );
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
      {error && <p role="alert">{error}</p>}
      {learnings !== null && learnings.length === 0 && <p>No learnings yet.</p>}
      <ul aria-label="Learnings">
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
