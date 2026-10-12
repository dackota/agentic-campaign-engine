import { useEffect, useRef, useState } from "react";
import { listAlerts, SignedOutError, type FiringAlert } from "./api";
import { messageOf } from "./messages";

const ALERT_POLL_MS = 2000;

/** Watch the alerts firing now; `error` is set while the last read failed. */
function useFiringAlerts(onSignedOut: () => void) {
  const [alerts, setAlerts] = useState<FiringAlert[]>([]);
  const [error, setError] = useState<string | null>(null);
  // The caller passes a new function each render; the polling must not restart for it.
  const signedOut = useRef(onSignedOut);
  signedOut.current = onSignedOut;

  useEffect(() => {
    let isActive = true;
    async function poll() {
      try {
        const found = await listAlerts();
        if (!isActive) return;
        setAlerts(found);
        setError(null);
      } catch (e) {
        if (!isActive) return;
        if (e instanceof SignedOutError) return signedOut.current();
        setError(messageOf(e));
      }
    }
    void poll();
    const timer = setInterval(() => void poll(), ALERT_POLL_MS);
    return () => {
      isActive = false;
      clearInterval(timer);
    };
  }, []);

  return { alerts, error };
}

/** A banner for each alert Grafana has fired and not yet resolved. Shows nothing when all is well. */
export function AlertBanner({ onSignedOut }: { onSignedOut: () => void }) {
  const { alerts, error } = useFiringAlerts(onSignedOut);
  if (alerts.length === 0 && error === null) return null;
  return (
    <section data-testid="alert-banner" role="alert" aria-label="Alerts">
      {error !== null && <p>Alerts could not be read: {error}</p>}
      <ul>
        {alerts.map((a) => (
          <li key={`${a.name}-${a.fired_at}`}>
            <strong>{a.name}</strong>: {a.summary}
          </li>
        ))}
      </ul>
    </section>
  );
}
