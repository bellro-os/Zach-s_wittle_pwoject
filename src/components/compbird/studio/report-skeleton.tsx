/**
 * Loading shimmer for the report area — mirrors the live layout so the page
 * never collapses while a dossier is fetched. Animation respects
 * prefers-reduced-motion via the [data-cb-anim] gate in compbird.css.
 */

function Bar({ className }: { className?: string }) {
  return (
    <div
      className={`rounded-md bg-secondary/70 animate-pulse motion-reduce:animate-none ${className ?? ""}`}
    />
  );
}

export function ReportSkeleton() {
  return (
    // The shimmer bars are decorative (aria-hidden below); the wrapper is a
    // polite status region so AT hears that a report is being fetched instead
    // of a silent, empty page.
    <div role="status" aria-live="polite">
      <span className="sr-only">Building the report…</span>
      <div aria-hidden className="flex flex-col gap-6">
      {/* subject header */}
      <div className="flex flex-col gap-3">
        <Bar className="h-5 w-28" />
        <Bar className="h-9 w-3/4" />
        <Bar className="h-4 w-1/2" />
      </div>

      <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
        {/* valuation */}
        <div className="flex flex-col gap-4 rounded-2xl border border-border bg-card/60 p-6">
          <Bar className="h-4 w-32" />
          <Bar className="h-14 w-2/3" />
          <Bar className="h-4 w-1/2" />
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
      <div className="flex flex-col gap-3 rounded-2xl border border-border bg-card/60 p-6">
        <Bar className="h-4 w-40" />
        {Array.from({ length: 5 }).map((_, i) => (
          <Bar key={i} className="h-9 w-full opacity-80" />
        ))}
      </div>
      </div>
    </div>
  );
}
