/**
 * Payload bounds for compbird's PUBLIC API routes (preview/generate/search/
 * streetview). Applied at the route layer, right where the body/query is parsed,
 * so a crafted or buggy payload can never push absurd numeric values into the
 * Python engine. Two idioms, on purpose:
 *
 *   - TUNING KNOBS (months/nComps/limit) are CLAMPED — never rejected — and
 *     anything non-numeric degrades to `undefined` so the engine defaults apply
 *     unchanged. They are preferences, not facts; a clamped knob is still a
 *     correct request.
 *   - SUBJECT FACTS + COORDINATES (sqft, beds, baths, acres, year_built,
 *     lat/lng) are REJECTED with a 400 + terse message when present but
 *     non-numeric, NaN/±Infinity, or outside plausibility bounds. Silently
 *     clamping a fact would move a valuation to a number the caller never
 *     asked for — a wrong answer is worse than an error.
 */

/** Route-layer bounds for the engine's numeric knobs. */
export const COMPBIRD_BOUNDS = {
  months: { min: 1, max: 60 },
  nComps: { min: 1, max: 12 },
  searchLimit: { min: 1, max: 25 },
} as const;

/**
 * Plausibility bounds for the numeric SUBJECT-FACT override fields the
 * preview/generate routes accept (`subjectOverrides`). Deliberately WIDER than
 * the engine-side clamp in @/lib/cma/overrides OVERRIDE_BOUNDS: this layer only
 * rejects the absurd (a 2^53 sqft, a negative year) with a 400; anything that
 * passes here is still tightened by sanitizeSubjectOverrides before the engine.
 */
export const SUBJECT_FACT_BOUNDS: Record<
  "sqft" | "bedrooms" | "full_baths" | "half_baths" | "acres" | "year_built",
  { min: number; max: number }
> = {
  sqft: { min: 100, max: 30000 },
  bedrooms: { min: 0, max: 30 },
  full_baths: { min: 0, max: 30 },
  half_baths: { min: 0, max: 30 },
  acres: { min: 0, max: 2000 },
  year_built: { min: 1700, max: 2035 },
};

/** Coordinate plausibility (streetview + any future geo param). */
export const GEO_BOUNDS = {
  lat: { min: -90, max: 90 },
  lng: { min: -180, max: 180 },
} as const;

/** Numeric coercion shared by the fact validators: number | numeric string → n, else NaN. */
function toNumber(v: unknown): number {
  if (typeof v === "number") return v;
  if (typeof v === "string" && v.trim() !== "") return Number(v);
  return NaN;
}

/**
 * Validate the NUMERIC fields of a `subjectOverrides` body against
 * SUBJECT_FACT_BOUNDS. Returns a terse, field-named error message (→ respond
 * 400) or `null` when the payload is acceptable. Absent/null/empty fields pass
 * (every override is optional); non-numeric values, NaN and ±Infinity are
 * rejected outright. Non-numeric fields (condition/property_type) are not this
 * function's concern — sanitizeSubjectOverrides allowlists those.
 */
export function subjectOverridesError(o: unknown): string | null {
  if (o == null) return null; // absent ⇒ no overrides, nothing to check
  if (typeof o !== "object" || Array.isArray(o)) {
    return "subjectOverrides must be an object";
  }
  for (const [field, bound] of Object.entries(SUBJECT_FACT_BOUNDS)) {
    const raw = (o as Record<string, unknown>)[field];
    if (raw == null || raw === "") continue;
    const n = toNumber(raw);
    if (!Number.isFinite(n)) return `${field} must be a finite number`;
    if (n < bound.min || n > bound.max) {
      return `${field} out of range (${bound.min}–${bound.max})`;
    }
  }
  return null;
}

/**
 * Parse a lat/lng query-param pair. Returns:
 *   - `null`            — both absent (caller decides; streetview 404s)
 *   - `{ error }`       — present but non-numeric/NaN/Infinity/implausible (→ 400)
 *   - `{ lat, lng }`    — plausible coordinates
 */
export function parseLatLng(
  latRaw: string | null,
  lngRaw: string | null,
): { lat: number; lng: number } | { error: string } | null {
  if ((latRaw == null || latRaw === "") && (lngRaw == null || lngRaw === "")) return null;
  const lat = toNumber(latRaw);
  const lng = toNumber(lngRaw);
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
    return { error: "lat/lng must be finite numbers" };
  }
  if (lat < GEO_BOUNDS.lat.min || lat > GEO_BOUNDS.lat.max) {
    return { error: "lat out of range (-90–90)" };
  }
  if (lng < GEO_BOUNDS.lng.min || lng > GEO_BOUNDS.lng.max) {
    return { error: "lng out of range (-180–180)" };
  }
  return { lat, lng };
}

/** Comp-address list caps: entries kept and max chars per entry. */
export const LIST_CAPS = { maxItems: 50, maxLen: 200 } as const;

/**
 * Identity/name string caps (chars) for the public routes. address/parcelId
 * match LIST_CAPS.maxLen (the same strings, singular); `agent` is a letterhead
 * name; `brand` is allowlisted downstream anyway (belt + suspenders here);
 * `runId` comfortably covers a cuid (~25 chars) — a longer string can never
 * name a real row, so truncation preserves the 404; `fileName` is the
 * filesystem's own 255-byte basename ceiling — a longer name cannot exist on
 * disk, so it's a nonsensical request (→ 400), not a miss.
 */
export const STRING_CAPS = {
  address: 200,
  parcelId: 200,
  brand: 40,
  agent: 120,
  runId: 64,
  fileName: 255,
} as const;

/**
 * Trim + length-cap a free-text string field (clamp, never 400 — a too-long
 * address is still an ask; its first 200 chars either resolve or they don't).
 * Non-string/empty input → `undefined`, so garbage degrades to "absent" and the
 * route's own absent-field handling applies unchanged.
 */
export function capString(v: unknown, maxLen: number): string | undefined {
  if (typeof v !== "string") return undefined;
  const s = v.trim().slice(0, maxLen);
  return s === "" ? undefined : s;
}

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
