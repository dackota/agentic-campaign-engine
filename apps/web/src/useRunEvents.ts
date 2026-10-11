import { useEffect, useRef, useState } from "react";
import { getCampaign, isFinalEvent, watchRun, type Campaign, type RunEvent } from "./api";
import { messageOf } from "./messages";

/** Follow a campaign's run: every step event so far while it runs, the refetched campaign at the end.
 * `resume` follows it again from the last event seen, after a retried step. */
export function useRunEvents(
  campaignId: string | undefined,
  onCampaign: (campaign: Campaign) => void,
  onError: (message: string) => void,
): { events: RunEvent[]; reset: () => void; resume: () => void } {
  const [events, setEvents] = useState<RunEvent[]>([]);
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
          setEvents((current) => [...current, event]);
        }
      },
      onError,
    );
    // The callbacks are stable setters from the caller; the run is keyed on the campaign
    // and the round, which `resume` moves on.
  }, [campaignId, round]);

  return {
    events,
    reset: () => {
      lastSeq.current = 0;
      setEvents([]);
    },
    resume: () => setRound((r) => r + 1),
  };
}
