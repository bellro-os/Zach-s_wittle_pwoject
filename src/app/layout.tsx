import type { Metadata } from "next";
import { Bricolage_Grotesque, Inter_Tight, JetBrains_Mono } from "next/font/google";
import { Toaster } from "sonner";
import "./globals.css";
import "@/styles/compbird.css";

/**
 * compbird — a standalone app; this root layout owns the whole document.
 * globals.css carries the Tailwind @theme wiring; compbird.css re-declares the
 * design tokens inside `.compbird-root` (on <body>), so every shared utility
 * renders in compbird's blue + light palette. Display = Bricolage Grotesque,
 * body = Inter Tight, figures = JetBrains Mono.
 */
const display = Bricolage_Grotesque({
  subsets: ["latin"],
  variable: "--font-cb-display",
  display: "swap",
});
const sans = Inter_Tight({
  subsets: ["latin"],
  variable: "--font-cb-sans",
  display: "swap",
});
const mono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-cb-mono",
  display: "swap",
});

const CB_TITLE = "compbird — property value, from altitude";
const CB_DESC =
  "compbird builds appraisal-grade comparables and live neighborhood market reports in seconds — a bird's-eye view of what every home is really worth.";

export const metadata: Metadata = {
  title: { default: CB_TITLE, template: "%s · compbird" },
  description: CB_DESC,
  openGraph: {
    type: "website",
    siteName: "compbird",
    title: CB_TITLE,
    description: CB_DESC,
  },
  twitter: {
    card: "summary_large_image",
    title: CB_TITLE,
    description: CB_DESC,
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={`${display.variable} ${sans.variable} ${mono.variable} compbird-root antialiased`}>
        {children}
        <Toaster richColors closeButton theme="light" />
      </body>
    </html>
  );
}
