"use client";

import { useId } from "react";
import { Pill } from "@/components/compbird/ui";
import { num } from "@/lib/compbird/format";
import type { ProfileFacts } from "@/lib/compbird/types";
import {
  CONDITION_LABELS,
  type CmaCondition,
  type SubjectOverrides,
} from "@/lib/cma/overrides";
import { cn } from "@/lib/utils/cn";

/**
 * "Adjust valuation (what-if)" — the agent-control panel on a LIVE report. v1
 * exposes the two value-moving subject facts: finished sqft and condition.
 *
 * These are WHAT-IF edits, not record truth. Each control reflects the record
 * value as its placeholder/default; only a value the agent actually changes is
 * emitted (so an untouched editor sends `{}` ⇒ a no-op override). Whenever a
 * field is edited the engine renders a record→adjusted disclosure server-side
 * (engine-locked, not toggleable) — this panel just drives the inputs.
 */

const CONDITION_OPTIONS = Object.entries(CONDITION_LABELS) as [
  CmaCondition,
  string,
][];

/** A small "Edited" pill + record→adjusted diff hint shown next to a changed field. */
function EditedHint({ hint }: { hint: string }) {
  return (
    <span className="inline-flex items-center gap-2">
      <Pill tone="ember">Edited</Pill>
      <span className="font-data text-xs text-muted-foreground">{hint}</span>
    </span>
  );
}

export function SubjectFactsEditor({
  facts,
  value,
  onChange,
}: {
  facts: ProfileFacts;
  value: SubjectOverrides;
  onChange: (next: SubjectOverrides) => void;
}) {
  const sqftId = useId();
  const conditionId = useId();

  const recordSqft = facts.sqft;
  // Only a value that DIFFERS from the record counts as edited — re-typing the
  // record value is a no-op (no badge, no wasted recompute, no disclosure).
  const sqftEdited = value.sqft != null && value.sqft !== recordSqft;
  const conditionEdited = value.condition != null;
  const anyEdited = sqftEdited || conditionEdited;

  /** Merge a patch, pruning keys set back to undefined so we only emit changes. */
  function patch(next: Partial<SubjectOverrides>) {
    const merged: SubjectOverrides = { ...value, ...next };
    for (const k of Object.keys(merged) as (keyof SubjectOverrides)[]) {
      if (merged[k] === undefined) delete merged[k];
    }
    onChange(merged);
  }

  function onSqftChange(raw: string) {
    const trimmed = raw.trim();
    if (trimmed === "") {
      patch({ sqft: undefined });
      return;
    }
    const n = Number(trimmed);
    if (!Number.isFinite(n)) return; // ignore non-numeric keystrokes
    // Typing the exact record value is a no-op — clear the override so it neither
    // badges as "Edited" nor fires a wasted recompute.
    patch({ sqft: n === recordSqft ? undefined : n });
  }

  function onConditionChange(raw: string) {
    // The empty option means "From record" ⇒ clear the override.
    patch({ condition: raw ? (raw as CmaCondition) : undefined });
  }

  function resetAll() {
    onChange({});
  }

  return (
    <section
      aria-labelledby={`${sqftId}-heading`}
      className="flex flex-col gap-4 rounded-xl border border-border/70 bg-secondary/30 p-3.5 sm:p-4"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <span className="cb-eyebrow text-muted-foreground" id={`${sqftId}-heading`}>
            Adjust valuation (what-if)
          </span>
          <p className="max-w-prose text-xs text-muted-foreground">
            Correct the record to see how the estimate moves. These adjust the
            estimate only — they don&apos;t change the public record, and any edit
            is disclosed on the report.
          </p>
        </div>
        {anyEdited ? (
          <button
            type="button"
            onClick={resetAll}
            className="shrink-0 text-xs font-medium text-[var(--cb-ember-text)] underline-offset-4 transition-colors hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]"
          >
            Reset all to record
          </button>
        ) : null}
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        {/* finished sqft */}
        <div className="flex flex-col gap-1.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <label
              htmlFor={sqftId}
              className="cb-eyebrow text-muted-foreground"
            >
              Finished sqft
            </label>
            {sqftEdited ? (
              <EditedHint
                hint={`${num(recordSqft)} → ${num(value.sqft)} sqft`}
              />
            ) : null}
          </div>
          <input
            id={sqftId}
            type="number"
            inputMode="numeric"
            min={100}
            max={25000}
            step={10}
            value={value.sqft ?? ""}
            onChange={(e) => onSqftChange(e.target.value)}
            placeholder={recordSqft != null ? num(recordSqft) : "Record sqft"}
            aria-label="Adjusted finished square footage (what-if)"
            autoComplete="off"
            className={cn(
              "font-data w-full rounded-xl border bg-card/70 px-3.5 py-2.5 text-sm text-foreground outline-none transition-colors placeholder:font-sans placeholder:text-muted-foreground focus:ring-1 focus:ring-[var(--cb-ember)]/30",
              sqftEdited
                ? "border-[var(--cb-ember)]/50"
                : "border-border focus:border-[var(--cb-ember)]/50",
            )}
          />
          {sqftEdited ? (
            <button
              type="button"
              onClick={() => patch({ sqft: undefined })}
              className="self-start text-[0.7rem] font-medium text-muted-foreground underline-offset-4 transition-colors hover:text-foreground hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]"
            >
              Reset to record
            </button>
          ) : null}
        </div>

        {/* condition */}
        <div className="flex flex-col gap-1.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <label
              htmlFor={conditionId}
              className="cb-eyebrow text-muted-foreground"
            >
              Condition
            </label>
            {conditionEdited ? (
              <EditedHint
                hint={`Record → ${CONDITION_LABELS[value.condition as CmaCondition]}`}
              />
            ) : null}
          </div>
          <select
            id={conditionId}
            value={value.condition ?? ""}
            onChange={(e) => onConditionChange(e.target.value)}
            aria-label="Adjusted condition (what-if)"
            className={cn(
              "font-data w-full appearance-none rounded-xl border bg-card/70 px-3.5 py-2.5 text-sm text-foreground outline-none transition-colors focus:ring-1 focus:ring-[var(--cb-ember)]/30",
              conditionEdited
                ? "border-[var(--cb-ember)]/50"
                : "border-border focus:border-[var(--cb-ember)]/50",
            )}
          >
            <option value="">From record</option>
            {CONDITION_OPTIONS.map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
          {conditionEdited ? (
            <button
              type="button"
              onClick={() => patch({ condition: undefined })}
              className="self-start text-[0.7rem] font-medium text-muted-foreground underline-offset-4 transition-colors hover:text-foreground hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]"
            >
              Reset to record
            </button>
          ) : null}
        </div>
      </div>
    </section>
  );
}

export default SubjectFactsEditor;
