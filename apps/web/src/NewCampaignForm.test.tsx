import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { NewCampaignForm } from "./NewCampaignForm";
import { stubApi } from "./testSupport";

const REASON = "Add your threat report to start the campaign.";
const create = () => screen.getByRole("button", { name: "Create campaign" }) as HTMLButtonElement;

test("the create button says why it is disabled until a report is added", async () => {
  stubApi({ "GET /workflows": [] });
  render(<NewCampaignForm onCreate={() => {}} />);

  expect(create().disabled).toBe(true);
  expect(screen.getByText(REASON)).toBeTruthy();
  expect(screen.getByText("Optional. The campaign pauses if it reaches this amount.")).toBeTruthy();

  await userEvent.type(screen.getByLabelText("Threat report"), "Something happened");
  expect(create().disabled).toBe(false);
  expect(screen.queryByText(REASON)).toBeNull();
});

test("a report of only spaces does not enable the button", async () => {
  stubApi({ "GET /workflows": [] });
  render(<NewCampaignForm onCreate={() => {}} />);
  await userEvent.type(screen.getByLabelText("Threat report"), "   ");
  expect(create().disabled).toBe(true);
});

test("the workflow picker names workflows in plain words and starts on the standard one", async () => {
  stubApi({ "GET /workflows": ["my-launch", "threat-report-to-campaign"] });
  render(<NewCampaignForm onCreate={() => {}} />);

  const picker = (await screen.findByRole("option", { name: "My launch" })).closest("select")!;
  expect(picker.selectedOptions[0]?.textContent).toBe("Threat report to campaign");
  const names = [...picker.options].map((o) => o.textContent);
  expect(names).toEqual(["My launch", "Threat report to campaign", "Quick email draft"]);
  expect(names).not.toContain("threat-report-to-campaign");
});

test("the standard workflow is offered even when no workflow is saved yet", async () => {
  stubApi({ "GET /workflows": [] });
  render(<NewCampaignForm onCreate={() => {}} />);
  expect(await screen.findByRole("option", { name: "Threat report to campaign" })).toBeTruthy();
});

test("a workflow list that cannot load says only the standard one is offered", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  stubApi({ "GET /workflows": new Response("boom", { status: 500 }) });
  render(<NewCampaignForm onCreate={() => {}} />);
  expect(await screen.findByText(/only the standard one is offered/)).toBeTruthy();
});

test("creating hands over the report, the chosen workflow and the budget", async () => {
  stubApi({ "GET /workflows": ["my-launch"] });
  const onCreate = vi.fn();
  render(<NewCampaignForm onCreate={onCreate} />);
  await screen.findByRole("option", { name: "My launch" });

  await userEvent.type(screen.getByLabelText("Threat report"), "Volt Typhoon");
  await userEvent.selectOptions(screen.getByLabelText("Workflow"), "my-launch");
  await userEvent.type(screen.getByLabelText("Budget (USD)"), "0.01");
  await userEvent.click(create());

  expect(onCreate).toHaveBeenCalledWith("Volt Typhoon", "my-launch", 0.01);
});

test("a blank budget is no limit, and the quick draft is the empty workflow name", async () => {
  stubApi({ "GET /workflows": [] });
  const onCreate = vi.fn();
  render(<NewCampaignForm onCreate={onCreate} />);
  await screen.findByRole("option", { name: "Threat report to campaign" });

  await userEvent.type(screen.getByLabelText("Threat report"), "Volt Typhoon");
  await userEvent.selectOptions(screen.getByLabelText("Workflow"), "Quick email draft");
  await userEvent.click(create());

  await waitFor(() => expect(onCreate).toHaveBeenCalledWith("Volt Typhoon", "", null));
});
