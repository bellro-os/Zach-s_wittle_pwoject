/**
 * compbird formatting helpers — all numeric output goes through here so figures
 * read consistently (tabular mono, sensible rounding) across the site.
 */

export function usd(n: number | null | undefined, fallback = "—"): string {
  if (n == null || !Number.isFinite(n)) return fallback;
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

export function ppsf(n: number | null | undefined, fallback = "—"): string {
  if (n == null || !Number.isFinite(n)) return fallback;
  return `$${Math.round(n)}`;
}

export function num(n: number | null | undefined, fallback = "—"): string {
  if (n == null || !Number.isFinite(n)) return fallback;
  return Math.round(n).toLocaleString("en-US");
}

export function num1(n: number | null | undefined, fallback = "—"): string {
  if (n == null || !Number.isFinite(n)) return fallback;
  return n.toLocaleString("en-US", { maximumFractionDigits: 1 });
}

/** Signed percent, e.g. +6.3% / -1.2%. */
export function pctDelta(n: number | null | undefined, fallback = "—"): string {
  if (n == null || !Number.isFinite(n)) return fallback;
  const v = n.toFixed(1);
  return `${n > 0 ? "+" : ""}${v}%`;
}

export function pct(n: number | null | undefined, fallback = "—"): string {
  if (n == null || !Number.isFinite(n)) return fallback;
  return `${n.toFixed(1)}%`;
}

export function miles(n: number | null | undefined, fallback = "—"): string {
  if (n == null || !Number.isFinite(n)) return fallback;
  return `${n.toFixed(1)} mi`;
}

export function sqft(n: number | null | undefined, fallback = "—"): string {
  if (n == null || !Number.isFinite(n)) return fallback;
  return `${Math.round(n).toLocaleString("en-US")} sqft`;
}

export function acres(n: number | null | undefined, fallback = "—"): string {
  if (n == null || !Number.isFinite(n)) return fallback;
  return `${n.toFixed(2)} ac`;
}

/**
 * Parse a feed date. A bare `YYYY-MM-DD` is parsed in LOCAL time so a close
 * date never slips a day west of UTC; full ISO timestamps pass through to the
 * native parser untouched.
 */
function parseFeedDate(d: string): Date {
  const m = d.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (m) {
    const [, y, mo, day] = m;
    return new Date(Number(y), Number(mo) - 1, Number(day));
  }
  return new Date(d);
}

/** "Mar 2025" from an ISO-ish date string. */
export function monthYear(d: string | null | undefined, fallback = "—"): string {
  if (!d) return fallback;
  const date = parseFeedDate(d);
  if (Number.isNaN(date.getTime())) return fallback;
  return date.toLocaleDateString("en-US", { month: "short", year: "numeric" });
}

/** "Mar 14, 2025". */
export function dateLong(d: string | null | undefined, fallback = "—"): string {
  if (!d) return fallback;
  const date = parseFeedDate(d);
  if (Number.isNaN(date.getTime())) return fallback;
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

/** Strip the inline <b>…</b> the engine may emit in valuation rationales. */
export function stripTags(s: string | null | undefined): string {
  return (s ?? "").replace(/<[^>]+>/g, "");
}

/** Title-case a county/city token from the data feed. */
export function titleCase(s: string | null | undefined, fallback = ""): string {
  if (!s) return fallback;
  return s
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .trim();
}

/**
 * Human labels for the MLS class enum the engine emits as `property_type`
 * (facts.property_type = the feed's `_class` token). Vocabulary matches the
 * engine's own UI labels (mls_bot buyer_portal/bands). NOTE: RE_1 spans
 * detached, townhouse AND condo listings in the feed, so it reads
 * "Residential" — "Single family" would mislabel ~13% of the class. Unknown
 * tokens fall back to a cleaned title-case (code suffix stripped), never the
 * raw enum.
 */
const PROPERTY_CLASS_LABELS: Record<string, string> = {
  RE_1: "Residential",
  MF_2: "Multifamily",
  LD_3: "Land",
  CM_4: "Commercial",
  FM_5: "Farm",
  RN_6: "Rental",
};

export function propertyTypeLabel(
  s: string | null | undefined,
  fallback = "",
): string {
  if (!s) return fallback;
  const token = s.trim().toUpperCase();
  const mapped = PROPERTY_CLASS_LABELS[token];
  if (mapped) return mapped;
  // Unknown class token: drop a trailing "_<n>" code suffix, break remaining
  // underscores into spaces, and title-case — readable words, never the enum.
  return titleCase(token.replace(/_\d+$/, "").replace(/_/g, " "), fallback);
}

/**
 * Join a place and its county field into one label WITHOUT ever fabricating
 * "X County" — some index rows carry an independent-city/locality name in the
 * county slot ("BLACKSBURG"), and appending the suffix minted impossible
 * labels ("Blacksburg County"). The county field renders title-cased AS-IS:
 * a value already ending in "County" keeps its suffix, anything else is
 * trusted to be the locality it says it is.
 * "Palmyra" + "Fluvanna County" → "Palmyra, Fluvanna County".
 * "" + "Fluvanna County" → "Fluvanna County" (no leading comma).
 * "BLACKSBURG" + "BLACKSBURG" → "Blacksburg" (no self-echo).
 */
export function placeLabel(
  name?: string | null,
  county?: string | null,
): string {
  const place = titleCase(name);
  const countyLabel = titleCase(county);
  if (place && countyLabel && place.toLowerCase() === countyLabel.toLowerCase()) return place;
  if (place && countyLabel) return `${place}, ${countyLabel}`;
  return place || countyLabel;
}

export function bedsBaths(
  beds: number | null | undefined,
  full: number | null | undefined,
  half: number | null | undefined,
): string {
  const parts: string[] = [];
  if (beds != null) parts.push(`${beds} bd`);
  if (full != null) {
    const total = full + (half ? half * 0.5 : 0);
    parts.push(`${total % 1 === 0 ? total : total.toFixed(1)} ba`);
  }
  return parts.join(" · ") || "—";
}
