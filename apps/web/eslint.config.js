import js from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  js.configs.recommended,
  ...tseslint.configs.recommended,
  { languageOptions: { globals: { ...globals.node, ...globals.browser } } },
  { files: ["**/*.ts", "**/*.tsx"], rules: { "max-lines-per-function": ["error", { max: 50 }] } },
  { ignores: ["node_modules/", "dist/", "playwright-report/", "test-results/"] },
);
