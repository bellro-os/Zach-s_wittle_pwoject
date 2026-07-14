import type { Metadata } from "next";
import { Inter, Instrument_Serif } from "next/font/google";
import Script from "next/script";
import "./globals.css";
import { ThemeProvider } from "@/components/theme-provider";
import { Nav } from "@/components/nav";
import { Toaster } from "@/components/ui/toaster";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const instrument = Instrument_Serif({
  weight: "400",
  style: ["normal", "italic"],
  subsets: ["latin"],
  variable: "--font-instrument",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Realtor Dashboard",
  description: "Daily call queue + lead-gen workflow",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    // Ratified "Ink & Emerald" is dark-only — `dark` is forced on <html> so
    // there is no light-mode regression. Font variables expose Inter (sans)
    // and Instrument Serif (the italic Accent serif).
    <html
      lang="en"
      className={`dark ${inter.variable} ${instrument.variable}`}
      suppressHydrationWarning
    >
      <body className="min-h-screen bg-ink-950 font-sans antialiased">
        {/* External script — loads before React hydrates. Avoids the
            "script tag inside React component" warning. The file lives at
            public/theme-init.js. */}
        <Script src="/theme-init.js" strategy="beforeInteractive" />
        <ThemeProvider>
          <Nav />
          <main className="mx-auto max-w-[1400px] px-5 py-6">{children}</main>
          <Toaster />
        </ThemeProvider>
      </body>
    </html>
  );
}
