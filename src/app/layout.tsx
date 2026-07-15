import type { Metadata } from "next";
import { Bricolage_Grotesque, Inter_Tight, JetBrains_Mono } from "next/font/google";
import { Toaster } from "sonner";
import { AnimationGovernor } from "@/components/compbird/animation-governor";
import { ConsentBanner } from "@/components/marketing/consent-banner";
import { MarketingPixels } from "@/components/marketing/pixels";
import { JsonLd } from "@/components/seo/json-ld";
import { siteSchema } from "@/lib/seo/schema";
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
  // Figures/mono glyphs are not above the fold — don't let this ~45KB woff2
  // compete with the LCP-critical display + sans fonts on first paint.
  preload: false,
});

// Lead with the query agents actually search ("CMA", "comps"), keep the brand.
const CB_TITLE = "Instant CMA & Comps for Real Estate Agents — compbird";
const CB_DESC =
  "Run an instant CMA in seconds. compbird gives real estate agents appraisal-grade comparable sales and live neighborhood market reports. Start free — no card.";

export const metadata: Metadata = {
  // Absolute base for OG/twitter image URLs in production (social scrapers
  // require absolute URLs; falls back to the dev origin locally).
  // Production canonical is the fallback (not localhost) so a missing/misspelled
  // env can never ship localhost OG-image/canonical URLs to crawlers.
  metadataBase: new URL(process.env.NEXT_PUBLIC_APP_URL?.trim() || "https://www.compbird.com"),
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
        {/* Site-wide structured data: Organization + WebSite + SoftwareApplication */}
        <JsonLd schema={siteSchema} />
        {children}
        {/* Pauses decorative [data-cb-anim] loops when the tab is hidden or idle */}
        <AnimationGovernor />
        <Toaster richColors closeButton theme="light" />
        {/* Ad pixels (consent-gated; inert without NEXT_PUBLIC_META_PIXEL_ID / NEXT_PUBLIC_GOOGLE_ADS_ID) */}
        <MarketingPixels />
        <ConsentBanner />
      </body>
    </html>
  );
}
