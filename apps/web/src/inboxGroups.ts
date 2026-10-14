import type { InboxAsset } from "./inboxApi.ts";

export interface CampaignGroup {
  campaignId: string;
  title: string;
  assets: InboxAsset[];
}

/** The inbox's assets under their campaign, in arrival order; the campaign a link opened first. */
export function groupByCampaign(assets: InboxAsset[], linked: string | null): CampaignGroup[] {
  const groups = new Map<string, CampaignGroup>();
  for (const a of assets) {
    const group = groups.get(a.campaign_id) ?? { campaignId: a.campaign_id, title: a.title, assets: [] };
    group.assets.push(a);
    groups.set(a.campaign_id, group);
  }
  return [...groups.values()].sort(
    (a, b) => Number(b.campaignId === linked) - Number(a.campaignId === linked),
  );
}

/** The assets of one campaign that the brand reviewer did not flag. */
export function cleanAssets(assets: InboxAsset[], campaignId: string): InboxAsset[] {
  return assets.filter((a) => a.campaign_id === campaignId && a.flags.length === 0);
}
