import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "vitest";
import { campaign, me } from "./testSupport";

// The hand-written fixtures stand in for the API. This keeps them honest: every field a
// fixture sends must still be a field of the Python response model that sends it, so a
// field renamed in the API fails here instead of passing against a stale fixture.
const API = resolve(dirname(fileURLToPath(import.meta.url)), "../../api/campaign_api");

/** The field names a pydantic model declares: the `name: type` lines of its class body. */
function modelFields(file: string, model: string): string[] {
  const source = readFileSync(resolve(API, file), "utf8");
  const body = new RegExp(`^class ${model}\\(BaseModel\\):\\n((?:(?:    .*)?\\n)*)`, "m").exec(source)?.[1];
  if (body === undefined) throw new Error(`no class ${model} in ${file}`);
  return [...body.matchAll(/^ {4}(\w+): /gm)].map((m) => m[1]!);
}

const CASES: [name: string, fixture: object, file: string, model: string][] = [
  ["campaign", campaign(), "main.py", "CampaignOut"],
  ["campaign ab_result", campaign().ab_result, "main.py", "AbResultOut"],
  ["campaign cost", campaign().cost, "budget.py", "CostOut"],
  ["me", me("owner"), "main.py", "Me"],
];

test.each(CASES)("the %s fixture sends only fields the API model has", (_name, fixture, file, model) => {
  const fields = modelFields(file, model);
  expect(fields.length).toBeGreaterThan(0);
  expect(Object.keys(fixture).filter((key) => !fields.includes(key))).toEqual([]);
});
