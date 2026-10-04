import type { NextConfig } from "next";

// `PAGES_DEMO=1` (set by the GitHub Pages workflow after `scripts/prepare-pages.mjs`) builds a
// static, login-free export of the sample-data pages.
const pagesDemo = process.env.PAGES_DEMO === "1";
const basePath = process.env.PAGES_BASE_PATH ?? "";

const nextConfig: NextConfig = pagesDemo
  ? {
      output: "export",
      basePath,
      trailingSlash: true,
      images: { unoptimized: true },
      reactStrictMode: true,
      // Server-only routes are stripped for this build, so type errors from them are expected.
      typescript: { ignoreBuildErrors: true },
    }
  : {
      typedRoutes: true,
      reactStrictMode: true,
    };

export default nextConfig;
