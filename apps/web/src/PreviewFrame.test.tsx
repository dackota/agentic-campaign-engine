import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { PreviewFrame } from "./PreviewFrame";

const frame = () => screen.getByTitle("Preview of Landing page") as HTMLIFrameElement;

test("a preview says Loading preview until its frame has loaded", async () => {
  vi.stubGlobal("fetch", async () => new Response("<h1>Hello</h1>"));
  render(<PreviewFrame title="Preview of Landing page" src="/api/p" />);

  const note = screen.getByRole("status");
  expect(note.textContent).toBe("Loading preview…");
  expect(note.className).toContain("block-loading");
  expect(frame().getAttribute("data-loaded")).toBe("false");

  // The page is fetched and handed to the frame; the note stays until the frame paints it.
  await waitFor(() => expect(frame().srcdoc).toBe("<h1>Hello</h1>"));
  expect(screen.queryByRole("status")).not.toBeNull();

  fireEvent.load(frame());
  expect(screen.queryByRole("status")).toBeNull();
  expect(frame().getAttribute("data-loaded")).toBe("true");
});

test("the frame is sandboxed with nothing allowed", () => {
  vi.stubGlobal("fetch", async () => new Response("<h1>Hello</h1>"));
  render(<PreviewFrame title="Preview of Landing page" src="/api/p" />);
  expect(frame().getAttribute("sandbox")).toBe("");
});

test("a preview that cannot load says what to do, and stops saying it is loading", async () => {
  vi.stubGlobal("fetch", async () => new Response("boom", { status: 500 }));
  render(<PreviewFrame title="Preview of Landing page" src="/api/p" />);

  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toBe("This preview could not be loaded. Reload the page to try again.");
  expect(alert.className).toContain("block-error");
  expect(screen.queryByRole("status")).toBeNull();
});
