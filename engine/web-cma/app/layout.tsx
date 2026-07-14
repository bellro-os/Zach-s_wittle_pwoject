import "./globals.css";
import type { Metadata } from "next";
import { Inter, Instrument_Serif } from "next/font/google";
import Link from "next/link";
import { Logo } from "@/components/ratified-ui";

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
  title: "CMA Search Dashboard",
  description: "Generate branded CMAs from MLS data.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${instrument.variable}`}>
      <body className="min-h-screen flex flex-col bg-ink-950 font-sans antialiased">
        <header className="sticky top-0 z-40 border-b border-white/10 bg-ink-950/80 backdrop-blur-xl">
          <div className="mx-auto max-w-6xl px-6 py-4 flex items-center justify-between">
            <Link href="/" className="flex items-center gap-3">
              <Logo className="h-9 w-9" />
              <div className="leading-tight">
                <div className="font-semibold tracking-tight text-white">Search Dashboard</div>
                <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">
                  White-label CMA generator
                </div>
              </div>
            </Link>
            <nav className="flex items-center gap-7 text-sm">
              <Link href="/" className="text-slate-400 transition-colors hover:text-white">
                Home
              </Link>
              <Link href="/cma/new" className="text-slate-400 transition-colors hover:text-white">
                New CMA
              </Link>
              <Link
                href="/cma/history"
                className="text-slate-400 transition-colors hover:text-white"
              >
                History
              </Link>
            </nav>
          </div>
        </header>
        <main className="flex-1 mx-auto max-w-6xl w-full px-6 py-8">{children}</main>
        <footer className="border-t border-white/10 bg-ink-950/60">
          <div className="mx-auto max-w-6xl px-6 py-5 text-[11px] uppercase tracking-[0.14em] text-slate-500 flex justify-between">
            <div>CMA Search Dashboard · localhost:3001</div>
            <div>Phase 4 preview · not production</div>
          </div>
        </footer>
      </body>
    </html>
  );
}
