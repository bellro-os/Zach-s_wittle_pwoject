import Link from "next/link";
import { listHistory, humanizeSlug } from "@/lib/history";
import { FadeIn, Accent } from "@/components/ratified-ui";

export const dynamic = "force-dynamic";

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export default async function HistoryPage() {
  const history = await listHistory(100);
  return (
    <div className="relative">
      {/* Header */}
      <div className="relative">
        <div className="pointer-events-none absolute inset-0 -z-10 bg-grid-fade" />
        <div className="pointer-events-none absolute -top-24 left-1/4 -z-10 h-64 w-64 rounded-full bg-emerald-500/15 blur-[120px]" />
        <FadeIn className="flex flex-col items-start gap-4 pb-8 pt-2">
          <span className="inline-flex items-center gap-2 rounded-full border border-emerald-500/25 bg-emerald-500/10 px-3.5 py-1 text-xs font-medium uppercase tracking-[0.18em] text-emerald-300">
            CMA history
          </span>
          <h1 className="max-w-2xl text-balance text-4xl font-semibold leading-[1.05] tracking-tight text-white sm:text-5xl">
            All <Accent>generated reports</Accent>
          </h1>
          <p className="max-w-xl text-balance text-base leading-relaxed text-slate-400">
            Sourced from <code className="rounded bg-white/[0.06] px-1.5 py-0.5 text-emerald-300">outputs/</code>.{" "}
            <span className="font-semibold text-white">{history.length}</span> report
            {history.length === 1 ? "" : "s"}.
          </p>
        </FadeIn>
      </div>

      {history.length === 0 ? (
        <FadeIn>
          <div className="rounded-2xl border border-dashed border-white/15 bg-ink-900/60 p-12 text-center text-sm text-slate-400">
            No CMAs generated yet.{" "}
            <Link
              href="/cma/new"
              className="font-medium text-emerald-300 underline-offset-4 hover:underline"
            >
              Generate your first one
            </Link>
            .
          </div>
        </FadeIn>
      ) : (
        <FadeIn>
          <div className="edge-light overflow-hidden rounded-2xl border border-white/10 bg-ink-900/80">
            <table className="w-full text-sm">
              <thead className="border-b border-white/10 bg-white/[0.03] text-[10px] uppercase tracking-wider text-slate-500">
                <tr>
                  <th className="px-4 py-3 text-left font-medium">Subject</th>
                  <th className="px-4 py-3 text-left font-medium">Brand</th>
                  <th className="px-4 py-3 text-left font-medium">PDF size</th>
                  <th className="px-4 py-3 text-left font-medium">Generated</th>
                  <th className="px-4 py-3 text-right font-medium">Files</th>
                </tr>
              </thead>
              <tbody>
                {history.map((r) => (
                  <tr
                    key={r.pdfName}
                    className="border-t border-white/8 transition-colors hover:bg-white/[0.02]"
                  >
                    <td className="px-4 py-3 font-medium text-white">{humanizeSlug(r.slug)}</td>
                    <td className="px-4 py-3 capitalize text-slate-400">{r.brand}</td>
                    <td className="px-4 py-3 text-slate-400">{formatBytes(r.size)}</td>
                    <td className="px-4 py-3 text-slate-400">
                      {new Date(r.mtime).toLocaleString()}
                    </td>
                    <td className="space-x-4 px-4 py-3 text-right">
                      <a
                        href={`/api/cma/pdf/${encodeURIComponent(r.pdfName)}`}
                        target="_blank"
                        rel="noreferrer"
                        className="font-medium text-emerald-300 transition-colors hover:text-emerald-200"
                      >
                        PDF
                      </a>
                      <a
                        href={`/api/cma/pdf/${encodeURIComponent(r.htmlName)}`}
                        target="_blank"
                        rel="noreferrer"
                        className="font-medium text-slate-400 transition-colors hover:text-white"
                      >
                        HTML
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </FadeIn>
      )}
    </div>
  );
}
