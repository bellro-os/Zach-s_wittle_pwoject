"use client";

import { useId } from "react";
import { Pill } from "@/components/compbird/ui";
import {
  NARRATIVE_CAPS,
  type ReportConfig,
} from "@/lib/cma/overrides";
import { cn } from "@/lib/utils/cn";

/**
 * Replace the auto-generated executive summary paragraph (reportConfig.execText)
 * on a LIVE report. Empty ⇒ the engine renders its own generated paragraph
 * ("Use auto-generated" clears the override). A character counter bounds the
 * input against NARRATIVE_CAPS.execText; the engine HTML-escapes the text and
 * the statutory disclaimer remains engine-locked regardless of this field.
 */

const MAX = NARRATIVE_CAPS.execText;

export function SummaryEditor({
  value,
  onChange,
}: {
  value: ReportConfig;
  onChange: (next: ReportConfig) => void;
}) {
  const id = useId();

  const text = value.execText ?? "";
  const edited = text.trim().length > 0;
  const remaining = MAX - text.length;
  const nearLimit = remaining <= 80;

  function onText(raw: string) {
    // Hard-cap on the client so the counter can never run negative; the route
    // re-clamps server-side via sanitizeReportConfig (defense in depth).
    const capped = raw.slice(0, MAX);
    const next: ReportConfig = { ...value };
    if (capped.trim()) next.execText = capped;
    else delete next.execText;
    onChange(next);
  }

  function reset() {
    const next: ReportConfig = { ...value };
    delete next.execText;
    onChange(next);
  }

  return (
    <section
      aria-labelledby={`${id}-heading`}
      className="flex flex-col gap-2.5 rounded-xl border border-border/70 bg-secondary/30 p-3.5 sm:p-4"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <span className="cb-eyebrow text-muted-foreground" id={`${id}-heading`}>
            Executive summary
          </span>
          <p className="max-w-prose text-xs text-muted-foreground">
            Replace the auto-written summary with your own framing for the client.
            Leave blank to use the generated paragraph.
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {edited ? <Pill tone="ember">Edited</Pill> : null}
          {edited ? (
            <button
              type="button"
              onClick={reset}
              className="text-xs font-medium text-[var(--cb-ember-text)] underline-offset-4 transition-colors hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]"
            >
              Use auto-generated
            </button>
          ) : null}
        </div>
      </div>

      <label htmlFor={id} className="sr-only">
        Executive summary text
      </label>
      <textarea
        id={id}
        value={text}
        onChange={(e) => onText(e.target.value)}
        rows={4}
        maxLength={MAX}
        placeholder="Auto-generated from the comp set and market context. Type to override…"
        aria-describedby={`${id}-count`}
        className={cn(
          "w-full resize-y rounded-xl border bg-card/70 px-3.5 py-2.5 text-sm leading-relaxed text-foreground outline-none transition-colors placeholder:text-muted-foreground focus:ring-1 focus:ring-[var(--cb-ember)]/30",
          edited
            ? "border-[var(--cb-ember)]/50"
            : "border-border focus:border-[var(--cb-ember)]/50",
        )}
      />
      <span
        id={`${id}-count`}
        aria-live="polite"
        className={cn(
          "font-data self-end text-[0.7rem] tabular-nums",
          nearLimit ? "text-[var(--cb-ember-text)]" : "text-muted-foreground",
        )}
      >
        {text.length.toLocaleString("en-US")} / {MAX.toLocaleString("en-US")}
      </span>
    </section>
  );
}

export default SummaryEditor;
