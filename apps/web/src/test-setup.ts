import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// Testing Library only unmounts by itself when the test globals are on; they are off here.
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
