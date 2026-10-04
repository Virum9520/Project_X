// Turns this checkout into a static, login-free build for GitHub Pages. DESTRUCTIVE: it deletes the
// server-only routes and overlays browser-only versions, so it only runs in CI (or with --force on
// a throwaway checkout). Never run it in your working tree.
//
// Run `scripts/export-practice-data.py` too (CI does): the practice pages load its JSON.
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

if (!process.env.CI && !process.argv.includes("--force")) {
  console.error(
    "prepare-pages deletes source files. Run it in CI or pass --force on a scratch checkout.",
  );
  process.exit(1);
}

const web = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = join(web, "src");

// Routes that need a server, a login or the API.
for (const p of [
  "app/(app)",
  "app/api",
  "app/onboarding",
  "app/sign-in",
  "app/sign-up",
  "app/recap",
  "app/dev",
  "app/healthz",
]) {
  rmSync(join(src, p), { recursive: true, force: true });
}
rmSync(join(src, "proxy.ts"), { force: true });

// Browser-only pages and modules, and the static files they use (the code-runner worker).
cpSync(join(web, "pages-demo/overlay/src"), src, { recursive: true });
cpSync(join(web, "pages-demo/overlay/public"), join(web, "public"), { recursive: true });

// Pyodide runs Python solutions in the browser; serve it from this site, like Monaco.
const pyodide = dirname(createRequire(import.meta.url).resolve("pyodide/package.json"));
mkdirSync(join(web, "public/pyodide"), { recursive: true });
for (const file of [
  "pyodide.mjs",
  "pyodide.asm.mjs",
  "pyodide.asm.wasm",
  "python_stdlib.zip",
  "pyodide-lock.json",
]) {
  cpSync(join(pyodide, file), join(web, "public/pyodide", file));
}

// The landing page's sign-up/sign-in buttons lead into the app instead.
const landing = join(src, "app/page.tsx");
if (existsSync(landing)) {
  writeFileSync(
    landing,
    readFileSync(landing, "utf8")
      .replaceAll('{ pathname: "/sign-up" }', '{ pathname: "/home" }')
      .replaceAll('{ pathname: "/sign-in" }', '{ pathname: "/garden" }'),
  );
}

if (!existsSync(join(web, "public/practice/bank.json"))) {
  console.warn("public/practice/bank.json is missing: run scripts/export-practice-data.py.");
}
console.log("Prepared static GitHub Pages build.");
