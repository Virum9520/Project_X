// Turns this checkout into a static, login-free build for GitHub Pages. DESTRUCTIVE: it deletes the
// server-only routes and overlays demo versions, so it only runs in CI (or with --force on a
// throwaway checkout). Never run it in your working tree.
import { cpSync, existsSync, readFileSync, rmSync, writeFileSync } from "node:fs";
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

cpSync(join(web, "pages-demo/overlay/src"), src, { recursive: true });

// The landing page's sign-up/sign-in buttons lead into the demo instead.
const landing = join(src, "app/page.tsx");
if (existsSync(landing)) {
  writeFileSync(
    landing,
    readFileSync(landing, "utf8")
      .replaceAll('{ pathname: "/sign-up" }', '{ pathname: "/home" }')
      .replaceAll('{ pathname: "/sign-in" }', '{ pathname: "/garden" }'),
  );
}
console.log("Prepared static GitHub Pages build.");
