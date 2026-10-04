import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  // The GitHub Pages overlay's pure modules reach src only through "@/", so they test here too.
  test: {
    include: ["src/**/*.test.ts", "pages-demo/overlay/src/**/*.test.ts"],
    environment: "node",
  },
});
