"use client";

import { useId } from "react";
import { Pill } from "@/components/compbird/ui";
import { num, num1, propertyTypeLabel } from "@/lib/compbird/format";
import type { ProfileFacts } from "@/lib/compbird/types";
import {
  CONDITION_LABELS,
  OVERRIDE_BOUNDS,
  type CmaCondition,
  type SubjectOverrides,
} from "@/lib/cma/overrides";
import { cn } from "@/lib/utils/cn";

/**
 * "Correct the record (what-if)" — the agent-control editor that now lives WITH
 * the subject identity block (you correct a fact where you read it). Exposes all
 * eight engine-accepted subject overrides: the two value-moving facts (finished
 * sqft + condition) plus bedrooms, full/half baths, acreage, year built and the
 * property-type label.
 *
 * These are WHAT-IF edits, not record truth. Each control reflects the record
 * value as its placeholder/default; only a value the agent actually CHANGES is
 * emitted (re-typing the record value is a no-op ⇒ no badge, no wasted
 * recompute, no disclosure). Whenever any field is edited the engine renders a
 * record→adjusted disclosure server-side (engine-locked, not toggleable) — this
 * editor just drives the inputs. Numeric bounds + integer/float mirror
 * OVERRIDE_BOUNDS; the route re-clamps everything (defense in depth).
 */

const CONDITION_OPTIONS = Object.entries(CONDITION_LABELS) as [
  CmaCondition,
  string,
][];

const PROPERTY_TYPE_MAX = 60;

/** A small "Edited" pill + record→adjusted diff hint shown next to a changed field. */
function EditedHint({ hint }: { hint: string }) {
  return (
    <span className="inline-flex items-center gap-2">
      <Pill tone="ember">Edited</Pill>
      <span className="font-data text-xs text-muted-foreground">{hint}</span>
    </span>
  );
}

/** Field wrapper: label + optional Edited hint above the control, Reset below. */
function Field({
  id,
  label,
  edited,
  hint,
  onReset,
  children,
}: {
  id: string;
  label: string;
  edited: boolean;
  hint?: string;
  onReset: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <label htmlFor={id} className="cb-eyebrow text-muted-foreground">
          {label}
        </label>
        {edited && hint ? <EditedHint hint={hint} /> : null}
      </div>
      {children}
      {edited ? (
        <button
          type="button"
          onClick={onReset}
          className="self-start text-[0.7rem] font-medium text-muted-foreground underline-offset-4 transition-colors hover:text-foreground hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]"
        >
          Reset to record
        </button>
      ) : null}
    </div>
  );
}

const inputBase =
  "font-data w-full rounded-xl border bg-card/70 px-3.5 py-2.5 text-sm text-foreground outline-none transition-colors placeholder:font-sans placeholder:text-muted-foreground focus:ring-1 focus:ring-[var(--cb-ember)]/30";
const editedBorder = "border-[var(--cb-ember)]/50";
const idleBorder = "border-border focus:border-[var(--cb-ember)]/50";

/** The six OVERRIDE_BOUNDS numeric fields, in display order. */
const NUM_FIELDS = [
  { key: "sqft", label: "Finished sqft", step: 10, unit: "sqft" },
  { key: "bedrooms", label: "Bedrooms", step: 1, unit: "bd" },
  { key: "full_baths", label: "Full baths", step: 1, unit: "full ba" },
  { key: "half_baths", label: "Half baths", step: 1, unit: "half ba" },
  { key: "acres", label: "Acreage", step: 0.01, unit: "ac" },
  { key: "year_built", label: "Year built", step: 1, unit: "" },
] as const;

type NumKey = (typeof NUM_FIELDS)[number]["key"];

/** Record value for a numeric override, read off the resolved facts. */
function recordFor(facts: ProfileFacts, key: NumKey): number | null {
  switch (key) {
    case "sqft":
      return facts.sqft;
    case "bedrooms":
      return facts.beds;
    case "full_baths":
      return facts.full_baths;
    case "half_baths":
      return facts.half_baths;
    case "acres":
      return facts.acres;
    case "year_built":
      return facts.year_built;
  }
}

/** Format a numeric value for the record→adjusted hint (acres keeps decimals). */
function fmtNum(key: NumKey, v: number | null | undefined): string {
  if (v == null) return "record";
  return key === "acres" ? num1(v) : num(v);
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
  const headingId = useId();
  const fieldPrefix = useId();

  const conditionEdited = value.condition != null;
  const recordType = facts.property_type;
  // property_type is edited when the free-text differs from the record's
  // HUMANIZED label (what the placeholder shows) — re-typing the label is a
  // no-op, matching the numeric fields' record-equality rule.
  const recordTypeLabel = recordType ? propertyTypeLabel(recordType) : "";
  const typeEdited =
    value.property_type != null &&
    value.property_type !== "" &&
    value.property_type !== recordTypeLabel;

  const numEdited = (key: NumKey) =>
    value[key] != null && value[key] !== recordFor(facts, key);

  const anyEdited =
    conditionEdited ||
    typeEdited ||
    NUM_FIELDS.some((f) => numEdited(f.key));

  /** Merge a patch, pruning keys set back to undefined so we only emit changes. */
  function patch(next: Partial<SubjectOverrides>) {
    const merged: SubjectOverrides = { ...value, ...next };
    for (const k of Object.keys(merged) as (keyof SubjectOverrides)[]) {
      if (merged[k] === undefined) delete merged[k];
    }
    onChange(merged);
  }

  function onNumChange(key: NumKey, raw: string) {
    const trimmed = raw.trim();
    if (trimmed === "") {
      patch({ [key]: undefined } as Partial<SubjectOverrides>);
      return;
    }
    const n = Number(trimmed);
    if (!Number.isFinite(n)) return; // ignore non-numeric keystrokes
    const record = recordFor(facts, key);
    // Typing the exact record value is a no-op — clear the override so it neither
    // badges as "Edited" nor fires a wasted recompute (generalized from the v1
    // sqft rule to every numeric field).
    patch({ [key]: n === record ? undefined : n } as Partial<SubjectOverrides>);
  }

  function onConditionChange(raw: string) {
    // The empty option means "From record" ⇒ clear the override.
    patch({ condition: raw ? (raw as CmaCondition) : undefined });
  }

  function onTypeChange(raw: string) {
    const capped = raw.slice(0, PROPERTY_TYPE_MAX);
    // Blank OR the record's own label ⇒ clear (no-op), matching the numeric rule.
    if (!capped.trim() || capped === recordTypeLabel) {
      patch({ property_type: undefined });
      return;
    }
    patch({ property_type: capped });
  }

  function resetAll() {
    onChange({});
  }

  return (
    <section
      aria-labelledby={headingId}
      className="flex flex-col gap-4 rounded-xl border border-border/70 bg-secondary/30 p-3.5 sm:p-4"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <span className="cb-eyebrow text-muted-foreground" id={headingId}>
            Correct the record (what-if)
          </span>
          <p className="max-w-prose text-xs text-muted-foreground">
            Correct any fact to see how the estimate moves. These adjust the
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
        {NUM_FIELDS.map((f) => {
          const id = `${fieldPrefix}-${f.key}`;
          const bound = OVERRIDE_BOUNDS[f.key];
          const record = recordFor(facts, f.key);
          const edited = numEdited(f.key);
          const cur = value[f.key];
          return (
            <Field
              key={f.key}
              id={id}
              label={f.label}
              edited={edited}
              hint={`${fmtNum(f.key, record)} → ${fmtNum(f.key, cur)}${f.unit ? ` ${f.unit}` : ""}`}
              onReset={() => patch({ [f.key]: undefined } as Partial<SubjectOverrides>)}
            >
              <input
                id={id}
                type="number"
                inputMode={bound.integer ? "numeric" : "decimal"}
                min={bound.min}
                max={bound.max}
                step={f.step}
                value={cur ?? ""}
                onChange={(e) => onNumChange(f.key, e.target.value)}
                placeholder={record != null ? fmtNum(f.key, record) : `Record ${f.label.toLowerCase()}`}
                aria-label={`Adjusted ${f.label.toLowerCase()} (what-if)`}
                autoComplete="off"
                className={cn(inputBase, edited ? editedBorder : idleBorder)}
              />
            </Field>
          );
        })}

        {/* condition — value-moving, maps to the engine appearance token */}
        <Field
          id={`${fieldPrefix}-condition`}
          label="Condition"
          edited={conditionEdited}
          hint={
            conditionEdited
              ? `Record → ${CONDITION_LABELS[value.condition as CmaCondition]}`
              : undefined
          }
          onReset={() => patch({ condition: undefined })}
        >
          <select
            id={`${fieldPrefix}-condition`}
            value={value.condition ?? ""}
            onChange={(e) => onConditionChange(e.target.value)}
            aria-label="Adjusted condition (what-if)"
            className={cn(
              inputBase,
              "appearance-none",
              conditionEdited ? editedBorder : idleBorder,
            )}
          >
            <option value="">From record</option>
            {CONDITION_OPTIONS.map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </Field>

        {/* property type — free-text class label, 60-char cap */}
        <Field
          id={`${fieldPrefix}-type`}
          label="Property type"
          edited={typeEdited}
          hint={
            typeEdited
              ? `${recordTypeLabel || "record"} → ${value.property_type}`
              : undefined
          }
          onReset={() => patch({ property_type: undefined })}
        >
          <input
            id={`${fieldPrefix}-type`}
            type="text"
            value={value.property_type ?? ""}
            onChange={(e) => onTypeChange(e.target.value)}
            maxLength={PROPERTY_TYPE_MAX}
            placeholder={recordTypeLabel || "Record property type"}
            aria-label="Adjusted property type (what-if)"
            autoComplete="off"
            className={cn(inputBase, typeEdited ? editedBorder : idleBorder)}
          />
        </Field>
      </div>
    </section>
  );
}

export default SubjectFactsEditor;
