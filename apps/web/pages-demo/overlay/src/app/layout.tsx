import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

import { SiteNav } from "@/components/site-nav";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

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
        <SiteNav />
        {children}
      </body>
    </html>
  );
}
