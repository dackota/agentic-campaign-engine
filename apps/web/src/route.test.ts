import assert from "node:assert/strict";
import { test } from "node:test";
import { parseRoute } from "./route.ts";

test("parseRoute never throws on malformed paths and falls back to home", () => {
  for (const path of ["/campaigns/%E0%A4%A", "/campaigns/%", "/campaigns/%zz", "/campaigns/%00", "", "/x/%"]) {
    assert.doesNotThrow(() => parseRoute(path), path);
  }
  assert.deepEqual(parseRoute("/campaigns/%E0%A4%A"), { page: "home" });
});

test("parseRoute reads the new page and a campaign id", () => {
  assert.deepEqual(parseRoute("/campaigns/new"), { page: "new" });
  assert.deepEqual(parseRoute("/campaigns/abc-1"), { page: "campaign", id: "abc-1" });
});
