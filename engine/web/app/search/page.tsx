import Link from "next/link";
import { Search as SearchIcon, Mic2 } from "lucide-react";
import { db } from "@/lib/data/db";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Accent, FadeIn, SectionHeading } from "@/components/ratified-ui";

interface TranscriptHit {
  recordingId: string;
  clientId: string;
  clientName: string;
  clientDisplayId: string;
  snippet: string;
  createdAt: Date;
}

function snippet(text: string, q: string, around = 90): string {
  const idx = text.toLowerCase().indexOf(q.toLowerCase());
  if (idx === -1) return text.slice(0, around * 2) + (text.length > around * 2 ? "…" : "");
  const start = Math.max(0, idx - around);
  const end = Math.min(text.length, idx + q.length + around);
  return (
    (start > 0 ? "…" : "") + text.slice(start, end) + (end < text.length ? "…" : "")
  );
}

export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string }>;
}) {
  const { q = "" } = await searchParams;
  const query = q.trim();

  let clientMatches: Awaited<ReturnType<typeof db.client.findMany>> = [];
  let transcriptHits: TranscriptHit[] = [];

  if (query.length >= 2) {
    const [clientsResult, recordingsResult] = await Promise.all([
      db.client.findMany({
        where: {
          deletedAt: null,
          OR: [
            { name: { contains: query } },
            { email: { contains: query } },
            { phone: { contains: query } },
            { altPhone: { contains: query } },
            { tags: { contains: query } },
          ],
        },
        take: 20,
      }),
      db.recording.findMany({
        where: {
          status: "done",
          transcript: { contains: query },
        },
        include: {
          client: { select: { id: true, name: true, displayId: true, deletedAt: true } },
        },
        orderBy: { createdAt: "desc" },
        take: 20,
      }),
    ]);
    clientMatches = clientsResult;
    transcriptHits = recordingsResult
      .filter((r) => r.client && !r.client.deletedAt && r.transcript)
      .map((r) => ({
        recordingId: r.id,
        clientId: r.clientId,
        clientName: r.client!.name,
        clientDisplayId: r.client!.displayId,
        snippet: snippet(r.transcript!, query),
        createdAt: r.createdAt,
      }));
  }

  const totalHits = clientMatches.length + transcriptHits.length;

  return (
    <div className="space-y-8">
      {/* Prominent search header */}
      <div className="relative overflow-hidden rounded-2xl border border-white/10 bg-ink-900/60 px-6 py-10 sm:px-10 sm:py-12">
        <div className="bg-grid-fade pointer-events-none absolute inset-0" aria-hidden />
        <div
          className="pointer-events-none absolute -top-24 left-1/2 h-64 w-[36rem] -translate-x-1/2 rounded-full bg-emerald-500/15 blur-[120px]"
          aria-hidden
        />
        <div className="relative flex flex-col items-center gap-6 text-center">
          <SectionHeading
            eyebrow="Search"
            title={
              <>
                Find <Accent>anyone, anything</Accent> across your book
              </>
            }
            sub="One field across your client roster and every recorded call — names, emails, tags, and transcript text."
          />
          <form action="/search" className="w-full max-w-2xl">
            <div className="relative">
              <SearchIcon className="absolute left-4 top-1/2 size-5 -translate-y-1/2 text-slate-500" />
              <input
                type="text"
                name="q"
                defaultValue={query}
                autoFocus
                placeholder="Address, owner, client name, transcript text..."
                className="h-12 w-full rounded-full border border-white/10 bg-ink-950/70 pl-12 pr-4 text-base text-(--color-foreground) placeholder:text-slate-500 transition-colors focus:border-emerald-500/40 focus:outline-none focus:ring-1 focus:ring-emerald-500/30"
              />
            </div>
          </form>
        </div>
      </div>

      {query ? (
        <>
          {clientMatches.length > 0 && (
            <FadeIn>
              <section>
                <h2 className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                  Clients ({clientMatches.length})
                </h2>
                <Card className="divide-y divide-white/10 py-0">
                  {clientMatches.map((c) => (
                    <Link
                      key={c.id}
                      href={`/clients/${c.id}`}
                      className="flex items-center justify-between p-3 transition-colors hover:bg-emerald-500/5"
                    >
                      <div>
                        <strong className="text-white">{c.name}</strong>
                        {c.phone ? ` · ${c.phone}` : ""}
                        {c.email ? ` · ${c.email}` : ""}
                        {c.tags && (
                          <span className="ml-2 text-xs text-slate-500">
                            {c.tags}
                          </span>
                        )}
                      </div>
                      <span className="font-mono text-xs text-slate-500">
                        {c.displayId}
                      </span>
                    </Link>
                  ))}
                </Card>
              </section>
            </FadeIn>
          )}

          {transcriptHits.length > 0 && (
            <FadeIn delay={0.05}>
              <section>
                <h2 className="mb-3 inline-flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                  <Mic2 className="size-4 text-emerald-300" /> Transcripts ({transcriptHits.length})
                </h2>
                <Card className="divide-y divide-white/10 py-0">
                  {transcriptHits.map((h) => (
                    <Link
                      key={h.recordingId}
                      href={`/clients/${h.clientId}`}
                      className="block p-3 transition-colors hover:bg-emerald-500/5"
                    >
                      <div className="flex items-center gap-2 text-sm">
                        <strong className="text-white">{h.clientName}</strong>
                        <Badge variant="secondary" className="text-[10px]">
                          {h.clientDisplayId}
                        </Badge>
                        <span className="ml-auto text-xs tabular-nums text-slate-500">
                          {h.createdAt.toISOString().slice(0, 10)}
                        </span>
                      </div>
                      <p
                        className="mt-1 line-clamp-2 text-xs text-slate-400"
                        dangerouslySetInnerHTML={{
                          __html: highlight(h.snippet, query),
                        }}
                      />
                    </Link>
                  ))}
                </Card>
              </section>
            </FadeIn>
          )}

          {totalHits === 0 && (
            <FadeIn>
              <Card className="p-12 text-center text-slate-400">
                No matches for{" "}
                <strong className="text-white">&ldquo;{query}&rdquo;</strong>.
                <p className="mt-2 text-xs text-slate-500">
                  Try a partial name, an email, a tag, or a phrase from a recorded call.
                </p>
              </Card>
            </FadeIn>
          )}
        </>
      ) : (
        <FadeIn>
          <Card className="space-y-2 p-8 text-slate-400">
            <p>
              <strong className="text-white">Search across:</strong>
            </p>
            <ul className="list-inside list-disc space-y-1 pl-2 text-sm">
              <li>Your client roster (name, email, phone, tags)</li>
              <li>Call transcripts — anything mentioned on a recorded call</li>
              <li>Prospect addresses and owner names (queue + property pages)</li>
            </ul>
            <p className="mt-3 border-t border-white/10 pt-2 text-xs">
              Property and parcel search lives in Tier 18 — for now use{" "}
              <Link href="/" className="text-emerald-300 underline decoration-emerald-500/40 underline-offset-2 hover:text-emerald-200">
                the call queue
              </Link>{" "}
              to find a parcel by signal.
            </p>
          </Card>
        </FadeIn>
      )}
    </div>
  );
}

/** HTML-escape and highlight occurrences of `q` in `text` with <mark>. */
function highlight(text: string, q: string): string {
  const escapeHtml = (s: string) =>
    s
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  const escaped = escapeHtml(text);
  const escapedQ = escapeHtml(q);
  const safeQ = escapedQ.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return escaped.replace(
    new RegExp(safeQ, "gi"),
    (m) => `<mark class="bg-emerald-500/20 text-emerald-200 px-0.5 rounded">${m}</mark>`,
  );
}
