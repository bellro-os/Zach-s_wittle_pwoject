import { dateLong } from "@/lib/compbird/format";
import type { Freshness } from "@/lib/compbird/freshness";

/**
 * A small, honest provenance stamp shown beneath the headline value: the MLS
 * pool refreshes hourly and is current to today, and — when the payload carries
 * it — the date of the newest comparable the estimate rests on. Reads as one
 * quiet line ("MLS data · refreshed hourly · most recent comparable closed …"),
 * never louder than the value it sits under. Sourced only from real dates: with
 * neither a comp close nor a meta as-of, it drops to the bare "refreshed hourly".
 *
 * Sample reports pass a `sample` flag so the stamp says "Sample MLS data" — a
 * fabricated dossier must never wear a live-data provenance line.
 */
export function DataFreshness({
  freshness,
  sample = false,
}: {
  freshness: Freshness;
  sample?: boolean;
}) {
  const { mostRecentClose, source } = freshness;
  const lead = sample ? "Sample MLS data" : "MLS data";
  const closed =
    !sample && mostRecentClose
      ? source === "comp_close"
        ? `most recent comparable closed ${dateLong(mostRecentClose)}`
        : `current as of ${dateLong(mostRecentClose)}`
      : null;

  return (
    <p className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
      <span
        className="h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--cb-ember)]/70"
        aria-hidden
      />
      <span>{lead}</span>
      <span aria-hidden className="text-border">
        ·
      </span>
      <span>refreshed hourly</span>
      {closed ? (
        <>
          <span aria-hidden className="text-border">
            ·
          </span>
          <span className="font-data">{closed}</span>
        </>
      ) : null}
    </p>
  );
}

export default DataFreshness;
