import assert from "node:assert/strict";
import { test } from "vitest";
import { cleanAssets, groupByCampaign } from "./inboxGroups.ts";
import type { InboxAsset } from "./inboxApi.ts";

const asset = (campaign_id: string, step: string, flagged = false): InboxAsset => ({
  campaign_id,
  title: `Campaign ${campaign_id}`,
  team: "t",
  created_by: "u",
  step,
  preview_url: null,
  output: {},
  flags: flagged ? [{ check: "banned_claim", detail: "x" }] : [],
  score: null,
  score_reason: null,
});

test("groups assets by campaign, the linked campaign first", () => {
  const groups = groupByCampaign([asset("a", "email_writer"), asset("b", "social"), asset("a", "one_pager")], "b");
  assert.deepEqual(
    groups.map((g) => [g.campaignId, g.assets.length]),
    [
      ["b", 1],
      ["a", 2],
    ],
  );
});

test("cleanAssets keeps only unflagged assets of one campaign", () => {
  const all = [asset("a", "email_writer"), asset("a", "social", true), asset("b", "one_pager")];
  assert.deepEqual(
    cleanAssets(all, "a").map((a) => a.step),
    ["email_writer"],
  );
});
