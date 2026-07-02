/**
 * Payload bounds for compbird's PUBLIC API routes (preview/generate/search).
 * Applied at the route layer, right where the body/query is parsed, so a crafted
 * or buggy payload can never push absurd numeric knobs or ballooned arrays into
 * the Python engine. Values are CLAMPED — never rejected — and anything
 * non-numeric degrades to `undefined` so the engine defaults apply unchanged.
 */

/** Route-layer bounds for the engine's numeric knobs. */
export const COMPBIRD_BOUNDS = {
  months: { min: 1, max: 60 },
  nComps: { min: 1, max: 12 },
  searchLimit: { min: 1, max: 25 },
} as const;

/** Comp-address list caps: entries kept and max chars per entry. */
export const LIST_CAPS = { maxItems: 50, maxLen: 200 } as const;

/**
 * Clamp a numeric knob to an integer in [min, max]. Absent/non-numeric/NaN input
 * → `undefined` (engine default) rather than a 400 — the knobs are tuning
 * parameters, not required fields.
 */
export function clampInt(
  v: unknown,
  { min, max }: { min: number; max: number },
): number | undefined {
  const n =
    typeof v === "number" ? v : typeof v === "string" && v.trim() !== "" ? Number(v) : NaN;
  if (!Number.isFinite(n)) return undefined;
  return Math.min(max, Math.max(min, Math.round(n)));
}

/**
 * Cap a comp-address list (`excluded`/`forced`): drop non-string entries, keep at
 * most the first LIST_CAPS.maxItems, truncate each to LIST_CAPS.maxLen chars.
 * Non-array input → `undefined` (engine treats it as absent).
 */
export function capStringList(v: unknown): string[] | undefined {
  if (!Array.isArray(v)) return undefined;
  return v
    .filter((s): s is string => typeof s === "string")
    .slice(0, LIST_CAPS.maxItems)
    .map((s) => s.slice(0, LIST_CAPS.maxLen));
}
