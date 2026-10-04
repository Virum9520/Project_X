import { ClerkProvider } from "@clerk/nextjs";
import { clerkAppearance } from "@sg/ui";
import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

import { SiteNav } from "@/components/site-nav";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Skill Garden",
  description: "Grow real skills. Every leaf is earned.",
  manifest: "/manifest.webmanifest",
  icons: { icon: "/icon.svg" },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col">
        <ClerkProvider appearance={clerkAppearance} signInUrl="/sign-in" signUpUrl="/sign-up">
          <SiteNav />
          {children}
        </ClerkProvider>
      </body>
    </html>
  );
}
