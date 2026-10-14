import { useEffect, useState, type ReactElement } from "react";
import { ErrorBlock, LoadingBlock } from "./ui";

type Loaded = { state: "loading" } | { state: "failed" } | { state: "ready"; html: string };

/** A sandboxed preview of a rendered asset, shared by the inbox and the run page.
 * The page is fetched here and handed to the frame as `srcdoc`, so the frame paints with the
 * page instead of waiting on a second request, and the sandbox stays fully closed. */
export function PreviewFrame({
  title,
  src,
  isTall = false,
}: {
  title: string;
  src: string;
  isTall?: boolean;
}): ReactElement {
  const [loaded, setLoaded] = useState<Loaded>({ state: "loading" });
  const [isPainted, setIsPainted] = useState(false);
  useEffect(() => {
    let isCurrent = true;
    setLoaded({ state: "loading" });
    setIsPainted(false);
    fetch(src)
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(String(r.status)))))
      .then((html) => isCurrent && setLoaded({ state: "ready", html }))
      .catch(() => isCurrent && setLoaded({ state: "failed" }));
    return () => {
      isCurrent = false;
    };
  }, [src]);

  return (
    <div className="preview-wrap">
      {!isPainted && loaded.state !== "failed" && <LoadingBlock>Loading preview…</LoadingBlock>}
      {loaded.state === "failed" && (
        <ErrorBlock>This preview could not be loaded. Reload the page to try again.</ErrorBlock>
      )}
      <iframe
        className={isTall ? "preview-frame preview-frame-tall" : "preview-frame"}
        title={title}
        srcDoc={loaded.state === "ready" ? loaded.html : undefined}
        sandbox=""
        data-loaded={isPainted}
        onLoad={() => loaded.state === "ready" && setIsPainted(true)}
      />
    </div>
  );
}
