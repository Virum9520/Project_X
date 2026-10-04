import { ClerkProvider } from "@clerk/nextjs";
import { clerkAppearance } from "@sg/ui";
import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Skill Garden · Owner Console",
  description: "Operations, usage and analytics for Skill Garden.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col">
        <ClerkProvider appearance={clerkAppearance} signInUrl="/sign-in">
          {children}
        </ClerkProvider>
      </body>
    </html>
  );
}
