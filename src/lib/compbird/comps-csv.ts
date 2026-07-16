import type { ProfileComp } from "@/lib/compbird/types";

/**
 * Comp-set CSV export for a SINGLE report — the studio's "Download comps (CSV)"
 * chip beside the comps-table heading (report-view.tsx). Pure string building,
 * no React/DOM, so it unit-tests under plain Node like the portfolio builder.
 *
 * The escaping is deliberately DUPLICATED from the portfolio export
 * (src/components/compbird/portfolio/csv.ts → csvCell) rather than imported —
 * that module is portfolio-owned plumbing with its own test surface. Keep the
 * two `csvCell` implementations in sync if the guard ever changes.
 */

function csvCell(v: string | number | null | undefined): string {
  if (v == null) return "";
  let s = String(v);
  // CSV formula-injection guard (launch security review 2026-07, P1): Excel /
  // Google Sheets execute cells that start with = + - @ (or a tab/CR-smuggled
  // variant) as formulas, so a crafted feed string (an address, a subdivision)
  // like `=HYPERLINK(...)` would run in the agent's spreadsheet. Neutralize by
  // prefixing a single quote — the spreadsheet-standard escape, which renders
  // the text verbatim. Applied only to STRING inputs: the numeric figure
  // columns arrive as numbers and can never start a formula.
  if (typeof v === "string" && /^[=+\-@\t\r]/.test(s)) s = `'${s}`;
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** Contract column order — mirrors the on-screen comps table left to right. */
export const COMPS_CSV_HEADER =
  "address,city,subdivision,sold_price,ppsf,sqft,acres,beds,baths,year_built,close_date,dom,distance_mi,match,source,flags";

/**
 * One row per comp in the CURRENT (tuned) valuation set. Unknown figures stay
 * empty — an honest blank, never a zero — matching the em-dash discipline of
 * the on-screen table. `match` is the engine similarity score when the set was
 * scored (CMA_COMP_SCORE_SURFACE=1); `flags` collects the honesty badges the
 * table shows as pills (pending / atypical).
 */
export function buildCompsCsv(comps: ProfileComp[]): string {
  const lines = [COMPS_CSV_HEADER];
  for (const c of comps) {
    const flags = [c.pending ? "pending" : null, c.atypical ? "atypical" : null]
      .filter(Boolean)
      .join(" ");
    lines.push(
      [
        csvCell(c.address),
        csvCell(c.city),
        csvCell(c.subdivision),
        csvCell(c.sold_price),
        csvCell(c.ppsf != null && Number.isFinite(c.ppsf) ? Math.round(c.ppsf) : null),
        csvCell(c.sqft),
        csvCell(c.acres),
        csvCell(c.beds),
        csvCell(c.baths),
        csvCell(c.year_built),
        csvCell(c.close_date),
        csvCell(c.dom),
        csvCell(
          c.distance_mi != null && Number.isFinite(c.distance_mi)
            ? Math.round(c.distance_mi * 10) / 10
            : null,
        ),
        csvCell(typeof c.similarity === "number" ? Math.round(c.similarity) : null),
        csvCell(c.source),
        csvCell(flags || null),
      ].join(","),
    );
  }
  return lines.join("\r\n");
}

/**
 * comps-509-jefferson-st-2026-07-15.csv — street line slugged, local date (it
 * names a download, not a record; same convention as portfolioCsvFilename).
 */
export function compsCsvFilename(address?: string | null, d: Date = new Date()): string {
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const slug = (address ?? "")
    .split(",")[0]
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
  return `comps${slug ? `-${slug}` : ""}-${d.getFullYear()}-${mm}-${dd}.csv`;
}
