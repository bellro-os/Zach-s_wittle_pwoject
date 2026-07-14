import Link from "next/link";
import { listBrands } from "@/lib/brands";
import { listHistory, humanizeSlug } from "@/lib/history";
import { FadeIn, SectionHeading, Accent, SpotCard } from "@/components/ratified-ui";

export const dynamic = "force-dynamic";

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function formatRelative(ms: number): string {
  const delta = Date.now() - ms;
  const mins = Math.floor(delta / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

export default async function HomePage() {
  const [brands, history] = await Promise.all([listBrands(), listHistory(8)]);
  const recent = history.slice(0, 8);

  return (
    <div className="space-y-20 sm:space-y-28">
      {/* ---------------------------------------------------------------- */}
      {/* Hero                                                             */}
      {/* ---------------------------------------------------------------- */}
      <section className="relative overflow-hidden">
        <div className="bg-grid-fade absolute inset-x-0 -top-24 h-[28rem]" aria-hidden />
        <div
          className="absolute -top-32 left-1/2 h-80 w-[44rem] -translate-x-1/2 rounded-full bg-emerald-500/15 blur-[120px]"
          aria-hidden
        />
        <div
          className="absolute -top-12 right-[6%] h-56 w-56 rounded-full bg-sky-500/10 blur-[100px]"
          aria-hidden
        />

        <div className="relative pt-10 sm:pt-16">
          <FadeIn className="flex flex-col items-center text-center">
            <span className="inline-flex items-center gap-2 rounded-full border border-emerald-500/25 bg-emerald-500/10 px-3.5 py-1 text-xs font-medium uppercase tracking-[0.18em] text-emerald-300">
              White-label CMA generator
            </span>
            <h1 className="mt-7 max-w-3xl text-balance text-5xl font-semibold leading-[1.05] tracking-tight text-white sm:text-6xl">
              From address to a <Accent>listing-ready</Accent> CMA
            </h1>
            <p className="mt-6 max-w-2xl text-balance text-lg leading-relaxed text-slate-400">
              Enter a subject address, pick a brand, and produce a one-page
              branded PDF in roughly 15 seconds — pulled straight from MLS data.
            </p>
          </FadeIn>

          <FadeIn delay={0.12} className="mt-10 grid gap-6 md:grid-cols-2">
            {/* Primary action card */}
            <Link href="/cma/new" className="group block">
              <div className="edge-light relative h-full overflow-hidden rounded-2xl border border-emerald-500/25 bg-emerald-500/[0.07] p-7 transition-all duration-300 hover:border-emerald-500/45 hover:bg-emerald-500/10">
                <div
                  className="absolute -right-10 -top-10 h-40 w-40 rounded-full bg-emerald-500/20 blur-[70px]"
                  aria-hidden
                />
                <div className="relative flex items-start justify-between gap-4">
                  <div>
                    <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-emerald-300/80">
                      Primary action
                    </div>
                    <div className="mt-2.5 text-2xl font-semibold tracking-tight text-white">
                      Generate a CMA
                    </div>
                    <p className="mt-2.5 max-w-sm text-sm leading-relaxed text-slate-300">
                      Subject address in, branded one-page PDF out — in about 15
                      seconds.
                    </p>
                    <span className="mt-5 inline-flex items-center gap-2 rounded-full bg-emerald-400 px-5 py-2.5 text-sm font-semibold text-ink-950 shadow-[0_0_28px_rgba(16,185,129,0.35)] transition-all duration-300 group-hover:bg-emerald-300 group-hover:shadow-[0_0_44px_rgba(16,185,129,0.5)]">
                      Start a new CMA
                      <svg
                        className="h-4 w-4 transition-transform duration-300 group-hover:translate-x-0.5"
                        viewBox="0 0 16 16"
                        fill="none"
                        aria-hidden
                      >
                        <path
                          d="M3 8h10m0 0L9 4m4 4-4 4"
                          stroke="currentColor"
                          strokeWidth="1.8"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    </span>
                  </div>
                </div>
              </div>
            </Link>

            {/* Brand profiles card */}
            <SpotCard className="p-7">
              <div className="flex items-baseline justify-between gap-3">
                <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-slate-500">
                  Brand profiles
                </div>
                <div className="text-[11px] uppercase tracking-wider text-slate-600">
                  config/brands
                </div>
              </div>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="text-3xl font-semibold tracking-tight text-white">
                  {brands.length}
                </span>
                <span className="text-sm text-slate-400">configured</span>
              </div>
              <div className="mt-5 space-y-2.5">
                {brands.length === 0 ? (
                  <p className="text-sm leading-relaxed text-slate-400">
                    No brands found. Add YAML files under{" "}
                    <code className="rounded bg-white/5 px-1.5 py-0.5 text-xs text-emerald-300">
                      config/brands/
                    </code>
                    .
                  </p>
                ) : (
                  brands.map((b) => (
                    <div
                      key={b.name}
                      className="flex items-center justify-between gap-3 rounded-xl border border-white/8 bg-white/[0.03] px-3.5 py-2.5 transition-colors hover:border-emerald-500/20"
                    >
                      <div className="flex items-center gap-3">
                        <span
                          className="size-4 rounded-md border border-white/10 ring-1 ring-white/5"
                          style={{ background: b.primary }}
                          aria-hidden
                        />
                        <span className="text-sm font-medium text-white">
                          {b.display_name}
                        </span>
                        <span className="text-[10px] uppercase tracking-wider text-slate-500">
                          {b.layout_style}
                        </span>
                      </div>
                      <span className="text-[11px] text-slate-500">
                        default: {b.agent_name || "—"}
                      </span>
                    </div>
                  ))
                )}
              </div>
            </SpotCard>
          </FadeIn>
        </div>
      </section>

      {/* ---------------------------------------------------------------- */}
      {/* Recent CMAs                                                      */}
      {/* ---------------------------------------------------------------- */}
      <section>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <SectionHeading
            align="left"
            eyebrow="History"
            title={
              <>
                Recently <Accent>generated</Accent>
              </>
            }
          />
          <FadeIn delay={0.1}>
            <Link
              href="/cma/history"
              className="group inline-flex items-center gap-1.5 text-sm font-medium text-emerald-300 transition-colors hover:text-emerald-200"
            >
              View all
              <svg
                className="h-3.5 w-3.5 transition-transform duration-300 group-hover:translate-x-0.5"
                viewBox="0 0 16 16"
                fill="none"
                aria-hidden
              >
                <path
                  d="M3 8h10m0 0L9 4m4 4-4 4"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </Link>
          </FadeIn>
        </div>

        <FadeIn delay={0.12} className="mt-8">
          {recent.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-white/12 bg-ink-900/40 p-10 text-center">
              <p className="text-sm text-slate-400">
                No CMAs generated yet. Click{" "}
                <Link
                  href="/cma/new"
                  className="font-medium text-emerald-300 underline-offset-4 hover:underline"
                >
                  Generate a CMA
                </Link>{" "}
                to make your first one.
              </p>
            </div>
          ) : (
            <div className="overflow-hidden rounded-2xl border border-white/10 bg-ink-900/80">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-white/10 text-left">
                    <th className="px-5 py-3.5 text-[10px] font-medium uppercase tracking-wider text-slate-500">
                      Subject
                    </th>
                    <th className="px-5 py-3.5 text-[10px] font-medium uppercase tracking-wider text-slate-500">
                      Brand
                    </th>
                    <th className="px-5 py-3.5 text-[10px] font-medium uppercase tracking-wider text-slate-500">
                      Size
                    </th>
                    <th className="px-5 py-3.5 text-[10px] font-medium uppercase tracking-wider text-slate-500">
                      Generated
                    </th>
                    <th className="px-5 py-3.5 text-right text-[10px] font-medium uppercase tracking-wider text-slate-500">
                      PDF
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {recent.map((r) => (
                    <tr
                      key={r.pdfName}
                      className="border-t border-white/[0.06] transition-colors hover:bg-white/[0.02]"
                    >
                      <td className="px-5 py-3 font-medium text-white">
                        {humanizeSlug(r.slug)}
                      </td>
                      <td className="px-5 py-3 capitalize text-slate-400">
                        {r.brand}
                      </td>
                      <td className="px-5 py-3 text-slate-500">
                        {formatBytes(r.size)}
                      </td>
                      <td className="px-5 py-3 text-slate-500">
                        {formatRelative(r.mtime)}
                      </td>
                      <td className="px-5 py-3 text-right">
                        <a
                          href={`/api/cma/pdf/${encodeURIComponent(r.pdfName)}`}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1.5 font-medium text-emerald-300 transition-colors hover:text-emerald-200"
                        >
                          Open
                          <svg
                            className="h-3 w-3"
                            viewBox="0 0 16 16"
                            fill="none"
                            aria-hidden
                          >
                            <path
                              d="M6 3h7v7M13 3 4 12"
                              stroke="currentColor"
                              strokeWidth="1.6"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                            />
                          </svg>
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </FadeIn>
      </section>
    </div>
  );
}
