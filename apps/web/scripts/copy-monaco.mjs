// Self-host Monaco: @monaco-editor/react otherwise fetches it from cdn.jsdelivr.net at runtime,
// which fails offline, behind a firewall or with an ad/content blocker, leaving "Loading editor…".
import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const web = join(dirname(fileURLToPath(import.meta.url)), "..");
const from = join(web, "node_modules/monaco-editor/min/vs");
const to = join(web, "public/monaco/vs");

if (!existsSync(from)) {
  console.error(`monaco-editor not found at ${from}; run pnpm install`);
  process.exit(1);
}
rmSync(to, { recursive: true, force: true });
mkdirSync(dirname(to), { recursive: true });
cpSync(from, to, { recursive: true });
console.log("Copied Monaco to public/monaco/vs");
