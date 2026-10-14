import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { test } from "vitest";

const css = readFileSync(resolve(import.meta.dirname, "styles.css"), "utf8");
const root = /:root\s*{([^}]*)}/.exec(css)?.[1] ?? "";

test("the stylesheet defines the design tokens, each with a value", () => {
  for (const token of ["--color-primary", "--space-2", "--font-size-md", "--radius", "--shadow"]) {
    assert.match(root, new RegExp(`${token}:\\s*\\S+`), token);
  }
});
