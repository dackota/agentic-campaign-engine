import { useState, type ReactElement } from "react";

/** A sandboxed preview of a rendered asset, shared by the inbox and the run page.
 * Until the frame has loaded it says so, so a slow render never looks like a blank box. */
export function PreviewFrame({
  title,
  src,
  isTall = false,
}: {
  title: string;
  src: string;
  isTall?: boolean;
}): ReactElement {
  const [isLoaded, setIsLoaded] = useState(false);
  return (
    <div className="preview-wrap">
      {!isLoaded && <p className="preview-loading" role="status">Loading preview…</p>}
      <iframe
        className={isTall ? "preview-frame preview-frame-tall" : "preview-frame"}
        title={title}
        src={src}
        sandbox=""
        data-loaded={isLoaded}
        onLoad={() => setIsLoaded(true)}
      />
    </div>
  );
}
