import type { ReactElement } from "react";

/** A sandboxed preview of a rendered asset, shared by the inbox and the run page. */
export function PreviewFrame({
  title,
  src,
  isTall = false,
}: {
  title: string;
  src: string;
  isTall?: boolean;
}): ReactElement {
  return <iframe className={isTall ? "preview-frame preview-frame-tall" : "preview-frame"} title={title} src={src} sandbox="" />;
}
