import { useEffect, useRef, useState } from "react";
import { getCampaign, isFinalEvent, watchRun, type Campaign, type RunEvent } from "./api";
import { messageOf } from "./messages";

/** Follow a campaign's run: per-step events while it runs, the refetched campaign at the end.
 * `resume` follows it again from the last event seen, after a retried step. */
export function useRunEvents(
  campaignId: string | undefined,
  onCampaign: (campaign: Campaign) => void,
  onError: (message: string) => void,
): { steps: Record<string, RunEvent>; reset: () => void; resume: () => void } {
  const [steps, setSteps] = useState<Record<string, RunEvent>>({});
  const [round, setRound] = useState(0);
  const lastSeq = useRef(0);

  useEffect(() => {
    if (!campaignId) return;
    return watchRun(
      campaignId,
      lastSeq.current,
      (event) => {
        lastSeq.current = Math.max(lastSeq.current, event.seq);
        if (isFinalEvent(event)) {
          getCampaign(campaignId).then(onCampaign, (e: unknown) => onError(messageOf(e)));
        } else {
          setSteps((current) => ({ ...current, [event.step]: event }));
        }
      },
      onError,
    );
    // The callbacks are stable setters from the caller; the run is keyed on the campaign
    // and the round, which `resume` moves on.
  }, [campaignId, round]);

  return {
    steps,
    reset: () => {
      lastSeq.current = 0;
      setSteps({});
    },
    resume: () => setRound((r) => r + 1),
  };
}
