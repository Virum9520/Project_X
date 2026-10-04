import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Script from "next/script";
import "./globals.css";

import { SiteNav } from "@/components/site-nav";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

/**
 * After a deploy, a browser can still hold the previous HTML (Pages caches it for 10 minutes),
 * whose script chunks no longer exist. Reload once to fetch the new page instead of showing an
 * error; the flag stops a reload loop and clears itself once a page has loaded.
 */
const RELOAD_ON_STALE_CHUNKS = `(function () {
  var KEY = "sg.stale-chunk-reload";
  var STALE = /ChunkLoadError|Loading chunk|Failed to load chunk|dynamically imported module/i;
  function retry(text) {
    if (!STALE.test(String(text || ""))) return;
    try {
      if (sessionStorage.getItem(KEY)) return;
      sessionStorage.setItem(KEY, "1");
    } catch (e) {
      return;
    }
    location.reload();
  }
  addEventListener("error", function (e) {
    retry(e.message || (e.error && e.error.name + ": " + e.error.message));
  });
  addEventListener("unhandledrejection", function (e) {
    var r = e.reason;
    retry(r && (r.name + ": " + r.message));
  });
  addEventListener("load", function () {
    setTimeout(function () {
      try {
        sessionStorage.removeItem(KEY);
      } catch (e) {}
    }, 10000);
  });
})();`;

export const metadata: Metadata = {
  title: "Skill Garden",
  description: "Grow real skills. Every leaf is earned.",
};

/**
 * GitHub Pages build: no sign-in and no API. The learner pages run in the browser on the sample
 * learner plus whatever is practised here (see `src/lib/practice`).
 */
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col">
        <Script id="sg-stale-chunk-reload" strategy="beforeInteractive">
          {RELOAD_ON_STALE_CHUNKS}
        </Script>
        <SiteNav />
        {children}
      </body>
    </html>
  );
}
