import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    // The GitHub Pages overlay stubs server actions with the same signatures.
    files: ["pages-demo/**"],
    rules: { "@typescript-eslint/no-unused-vars": ["warn", { argsIgnorePattern: "^_" }] },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Static files the GitHub Pages build copies in (the code-runner worker is plain JS).
    "pages-demo/overlay/public/**",
    // Self-hosted Monaco copied by scripts/copy-monaco.mjs.
    "public/monaco/**",
  ]),
]);

export default eslintConfig;
