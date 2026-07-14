/**
 * Loading shimmer for the report area — mirrors the live layout so the page
 * never collapses while a dossier is fetched. Animation respects
 * prefers-reduced-motion via the [data-cb-anim] gate in compbird.css.
 *
 * Progressive first paint: when the lookup's identity is known (an ?address=
 * deep link, a retry, a recents chip) the ADDRESS paints as real text in the
 * headline slot, and the valuation slot always renders the honest
 * `EstimateWorkingState` ("Running comp analysis…") instead of anonymous bars.
 * ONE NUMBER EVERYWHERE: the estimate slot never shows a provisional figure —
 * only an explicit working state until the real number exists.
 *
 * Selections that carry a full PropertyMatch don't land here at all — they get
 * the richer <SubjectPreview> (subject-preview.tsx), which shares the
 * `Bar` / `EstimateWorkingState` idioms exported below.
 */

export function Bar({ className }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={`rounded-md bg-secondary/70 animate-pulse motion-reduce:animate-none ${className ?? ""}`}
    />
  );
}

/**
 * The estimate slot's honest working state — shared by the plain skeleton and
 * the subject preview so "the number is being computed" reads identically on
 * both loading paths. A shimmer holds the hero figure's space (h-12/h-14 ≈ the
 * text-5xl/6xl hero in valuation-panel.tsx) and the copy names the work;
 * NEVER a placeholder number.
 *
 * After ~6s (`slow`, timed by the studio) one quiet honesty line is appended —
 * true: a first analysis runs the cold hygiene+blind path server-side and the
 * result is cached per subject afterwards. The text lives in a polite status
 * region so AT hears the working state and the slow-lookup addition.
 */
export function EstimateWorkingState({ slow = false }: { slow?: boolean }) {
  return (
    <div className="flex flex-col">
      <span className="cb-eyebrow text-muted-foreground">Estimated value</span>
      {/* hero-figure stand-in — space only, never a number */}
      <Bar className="mt-2 h-12 w-2/3 sm:h-14" />
      <div role="status" aria-live="polite">
        <p className="mt-2.5 flex items-center gap-2 text-sm text-muted-foreground">
          <span
            className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-[var(--cb-ember)] motion-reduce:animate-none"
            aria-hidden
          />
          Running comp analysis — pricing against nearby sales…
        </p>
        {slow ? (
          <p className="mt-2 text-xs text-muted-foreground/80">
            First analysis of a property takes a few extra seconds — the result
            is cached after this.
          </p>
        ) : null}
      </div>
    </div>
  );
}

/** ZONE-2 stand-in (comps table) — shared with the subject preview. */
export function EvidenceSkeleton() {
  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-border bg-card/60 p-6">
      <Bar className="h-4 w-40" />
      {Array.from({ length: 5 }).map((_, i) => (
        <Bar key={i} className="h-9 w-full opacity-80" />
      ))}
    </div>
  );
}

export function ReportSkeleton({
  pendingAddress = null,
  slow = false,
}: {
  /** The address being looked up, when known — paints as real headline text. */
  pendingAddress?: string | null;
  /** The lookup has been pending ~6s — show the honest first-analysis line. */
  slow?: boolean;
}) {
  return (
    // The shimmer bars are decorative (each Bar is aria-hidden); a polite
    // status region tells AT a report is being fetched instead of a silent,
    // empty page. Sibling — not wrapping — so the EstimateWorkingState's own
    // status region below isn't nested inside another live region.
    <div>
      <p role="status" aria-live="polite" className="sr-only">
        {pendingAddress ? `Building the report for ${pendingAddress}…` : "Building the report…"}
      </p>
      <div className="flex flex-col gap-6">
        {/* subject header — the looked-up address paints as real text when known */}
        <div className="flex flex-col gap-3">
          <Bar className="h-5 w-28" />
          {pendingAddress ? (
            <h2 className="font-display text-3xl font-bold leading-tight tracking-tight text-foreground text-balance sm:text-4xl">
              {pendingAddress}
            </h2>
          ) : (
            <Bar className="h-9 w-3/4" />
          )}
          <Bar className="h-4 w-1/2" />
        </div>

        <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
          {/* valuation — an honest working state, never a placeholder number */}
          <div className="flex flex-col gap-4 rounded-2xl border border-border bg-card/60 p-6">
            <EstimateWorkingState slow={slow} />
            <div className="mt-2 flex flex-col gap-3 border-t border-border pt-4">
              <Bar className="h-4 w-full" />
              <Bar className="h-4 w-5/6" />
              <Bar className="h-4 w-4/6" />
            </div>
          </div>
          {/* map */}
          <Bar className="h-64 w-full rounded-2xl lg:h-full" />
        </div>

        {/* table */}
        <EvidenceSkeleton />
      </div>
    </div>
  );
}
