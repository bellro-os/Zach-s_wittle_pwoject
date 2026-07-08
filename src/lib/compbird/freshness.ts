/**
 * Honest data-freshness read for the studio. The MLS pool refreshes hourly and
 * is current to today; the ONE date we can truthfully surface is the newest
 * comparable's close date (the most recent sale the estimate rests on). We
 * source it from the payload — never fabricate a timestamp not in the data.
 *
 * Preference order: the newest comp `close_date` (the honest "evidence is
 * current to…" signal), then `meta.as_of` as a fallback engine stamp. When
 * neither exists the stamp degrades to the bare "refreshed hourly" line.
 */
import type { ProfileResult } from "./types";

export interface Freshness {
  /** The newest comparable's close date (ISO-ish), or the meta as-of fallback. */
  mostRecentClose: string | null;
  /** Which field the date came from — drives the phrasing of the stamp. */
  source: "comp_close" | "meta_as_of" | null;
}

/**
 * Pull the newest sale date out of a resolved profile. Prefers the latest comp
 * close_date; falls back to meta.as_of. A locked profile carries no comp rows,
 * so it lands on the meta fallback — still honest, never invented.
 */
export function readFreshness(profile: ProfileResult): Freshness {
  let newest: string | null = null;
  let newestT = -Infinity;
  for (const c of profile.comps ?? []) {
    const d = c.close_date;
    if (!d) continue;
    const t = Date.parse(d);
    if (!Number.isFinite(t)) continue;
    if (t > newestT) {
      newestT = t;
      newest = d;
    }
  }
  if (newest) return { mostRecentClose: newest, source: "comp_close" };
  const asOf = profile.meta?.as_of ?? null;
  if (asOf) return { mostRecentClose: asOf, source: "meta_as_of" };
  return { mostRecentClose: null, source: null };
}
