import { useEffect, useState } from "react";

/** Where the Campaigns tab is: the home list, the new-campaign page, or one campaign. */
export type Route = { page: "home" } | { page: "new" } | { page: "campaign"; id: string };

const CAMPAIGN_PATH = /^\/campaigns\/([^/]+)\/?$/;

export function parseRoute(pathname: string): Route {
  if (/^\/campaigns\/new\/?$/.test(pathname)) return { page: "new" };
  const id = CAMPAIGN_PATH.exec(pathname)?.[1];
  if (!id) return { page: "home" };
  try {
    return { page: "campaign", id: decodeURIComponent(id) };
  } catch {
    // A mistyped or mangled link: show home rather than crash the app.
    return { page: "home" };
  }
}

export const campaignPath = (id: string): string => `/campaigns/${encodeURIComponent(id)}`;
export const NEW_CAMPAIGN_PATH = "/campaigns/new";

/** The route from the address bar; `go` moves to a path without a page load. */
export function useRoute(): { route: Route; go: (path: string) => void } {
  const [route, setRoute] = useState(() => parseRoute(window.location.pathname));
  useEffect(() => {
    const onPop = () => setRoute(parseRoute(window.location.pathname));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  return {
    route,
    go: (path) => {
      if (path !== window.location.pathname) window.history.pushState(null, "", path);
      setRoute(parseRoute(path));
    },
  };
}
