import { useEffect, useState } from "react";
import { getCampaign, isFinalEvent, watchRun, type Campaign, type RunEvent } from "./api";
import { messageOf } from "./messages";

/** Follow a campaign's run: per-step events while it runs, the refetched campaign at the end. */
export function useRunEvents(
  campaignId: string | undefined,
  onCampaign: (campaign: Campaign) => void,
  onError: (message: string) => void,
): { steps: Record<string, RunEvent>; reset: () => void } {
  const [steps, setSteps] = useState<Record<string, RunEvent>>({});

  useEffect(() => {
    if (!campaignId) return;
    return watchRun(
      campaignId,
      (event) => {
        if (isFinalEvent(event)) {
          getCampaign(campaignId).then(onCampaign, (e: unknown) => onError(messageOf(e)));
        } else {
          setSteps((current) => ({ ...current, [event.step]: event }));
        }
      },
      onError,
    );
    // The callbacks are stable setters from the caller; the run is keyed on the campaign alone.
  }, [campaignId]);

  return { steps, reset: () => setSteps({}) };
}
