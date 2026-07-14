import type { PortfolioItemDto as PortfolioItem } from "@/lib/compbird/portfolio";

/**
 * Pure input/output plumbing for the portfolio page — textarea line parsing,
 * client-side CSV upload parsing, the dedupe/cap queue builder, the results
 * CSV export builder, and the totals math the footer row renders. No React,
 * no DOM: everything here is exercised directly by the render fixture.
 */

/** Hard cap on a single portfolio run — mirrors the API contract (1..50). */
export const PORTFOLIO_CAP = 50;

export interface ParsedEntry {
  address: string;
  label?: string;
}

/** Dedupe identity for an address line: trimmed, squashed, case-folded. */
function keyOf(address: string): string {
  return address.trim().replace(/\s+/g, " ").toLowerCase();
}

/**
 * Textarea input: one address per line. Whole line = the address (street
 * addresses carry commas, so there is no inline label syntax here — labels
 * come from the CSV path). Blank lines dropped, whitespace squashed.
 *
 * ONE exception: a line that STARTS with a double quote is a CSV-style row
 * ("addr, with, commas", label) — pasted from a spreadsheet cell or the
 * empty-state example — and parses as address + optional label. Unambiguous:
 * no street address begins with a quote character.
 */
export function parseAddressLines(text: string): ParsedEntry[] {
  return text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean)
    .map((line) => {
      if (line.startsWith('"')) {
        const [entry] = parseCsv(line);
        if (entry) return entry;
      }
      return { address: line.replace(/\s+/g, " ") };
    });
}

/**
 * Minimal RFC-4180-ish CSV parser (quoted fields, embedded commas/quotes/
 * newlines). First column = address, optional second column = label; any
 * further columns are ignored. A leading header row is skipped when the first
 * cell reads like one ("address", "property", …) or the second reads "label".
 */
export function parseCsv(text: string): ParsedEntry[] {
  const rows: string[][] = [];
  let field = "";
  let row: string[] = [];
  let inQuotes = false;

  const pushField = () => {
    row.push(field);
    field = "";
  };
  const pushRow = () => {
    pushField();
    // Ignore rows that are entirely empty (trailing newline artifacts).
    if (row.some((f) => f.trim() !== "")) rows.push(row);
    row = [];
  };

  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i++; // escaped quote
        } else {
          inQuotes = false;
        }
      } else {
        field += ch;
      }
    } else if (ch === '"') {
      inQuotes = true;
    } else if (ch === ",") {
      pushField();
    } else if (ch === "\n") {
      pushRow();
    } else if (ch !== "\r") {
      field += ch;
    }
  }
  if (field !== "" || row.length) pushRow();

  if (!rows.length) return [];

  const first = rows[0];
  const headCell = (first[0] ?? "").trim().toLowerCase();
  const headLabel = (first[1] ?? "").trim().toLowerCase();
  const isHeader =
    /^(address|street address|property address|property|addr|site address)$/.test(headCell) ||
    headLabel === "label";
  const data = isHeader ? rows.slice(1) : rows;

  const out: ParsedEntry[] = [];
  for (const r of data) {
    const address = (r[0] ?? "").trim().replace(/\s+/g, " ");
    if (!address) continue;
    const label = (r[1] ?? "").trim();
    out.push(label ? { address, label } : { address });
  }
  return out;
}

export interface PortfolioQueue {
  items: ParsedEntry[];
  /** Identical addresses collapsed (first occurrence wins; a later label backfills). */
  duplicates: number;
  /** Entries beyond the 50 cap, trimmed off the end. */
  trimmed: number;
}

/**
 * Merge every input source into the run queue: dedupe identical addresses
 * (case/whitespace-insensitive; the first occurrence wins, but a labelled
 * duplicate donates its label to an unlabelled keeper), then cap at 50.
 */
export function buildQueue(entries: ParsedEntry[], cap: number = PORTFOLIO_CAP): PortfolioQueue {
  const seen = new Map<string, ParsedEntry>();
  let duplicates = 0;
  for (const e of entries) {
    const k = keyOf(e.address);
    const prior = seen.get(k);
    if (prior) {
      duplicates++;
      if (!prior.label && e.label) prior.label = e.label;
    } else {
      seen.set(k, { ...e });
    }
  }
  const deduped = Array.from(seen.values());
  const items = deduped.slice(0, cap);
  return { items, duplicates, trimmed: Math.max(0, deduped.length - cap) };
}

/* ── First-visit empty state ─────────────────────────────────────────────── */

/**
 * The three ghost example lines the empty state shows — and what "Try an
 * example" pastes into the textarea verbatim. Real-looking New River Valley
 * addresses; the third demonstrates the CSV label column (quoted address,
 * label after the comma — parseAddressLines understands that form, so the
 * pasted example round-trips with its label intact and clearly marked).
 */
export const PORTFOLIO_EXAMPLE_LINES = [
  "509 Jefferson St, Blacksburg, VA 24060",
  "1203 Walnut Ridge Rd, Christiansburg, VA 24073",
  '"612 Amherst Ave, Blacksburg, VA 24060", Example — rental unit',
] as const;

/** The textarea fill for "Try an example". */
export const PORTFOLIO_EXAMPLE_TEXT = PORTFOLIO_EXAMPLE_LINES.join("\n");

/**
 * First-visit predicate: the inviting empty state shows only while the panel
 * is truly untouched — nothing typed (whitespace doesn't count as typing), no
 * CSV parsed, and no previous run to pick up from. Any of those three and the
 * treatment gets out of the way.
 */
export function showPortfolioEmptyState(args: {
  hasRuns: boolean;
  text: string;
  csvCount: number;
}): boolean {
  return !args.hasRuns && args.text.trim() === "" && args.csvCount === 0;
}

/* ── Results export ──────────────────────────────────────────────────────── */

function csvCell(v: string | number | null | undefined): string {
  if (v == null) return "";
  let s = String(v);
  // CSV formula-injection guard (launch security review 2026-07, P1): Excel /
  // Google Sheets execute cells that start with = + - @ (or a tab/CR-smuggled
  // variant) as formulas, so a crafted portfolio LABEL like
  // `=HYPERLINK(...)` would run in the analyst's spreadsheet. Neutralize by
  // prefixing a single quote — the spreadsheet-standard escape, which renders
  // the text verbatim. Applied only to STRING inputs: the numeric figure
  // columns arrive as numbers and can never start a formula.
  if (typeof v === "string" && /^[=+\-@\t\r]/.test(s)) s = `'${s}`;
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export const RESULTS_CSV_HEADER =
  "label,address,parcel,mid,low,high,confidence,comps,nearest_mi,avg_match";

/**
 * The download: one row per portfolio item, contract column order. Rows that
 * never comped (error/pending) keep their identity columns and leave the
 * figures empty — an honest blank, never a zero.
 */
export function buildResultsCsv(items: PortfolioItem[]): string {
  const lines = [RESULTS_CSV_HEADER];
  for (const it of items) {
    const done = it.status === "done";
    lines.push(
      [
        csvCell(it.label),
        csvCell(it.resolvedAddress ?? it.inputAddress),
        csvCell(it.parcelId),
        csvCell(done ? it.mid : null),
        csvCell(done ? it.low : null),
        csvCell(done ? it.high : null),
        csvCell(done ? it.confidenceTier : null),
        csvCell(done ? it.compCount : null),
        csvCell(done && it.nearestMi != null ? Math.round(it.nearestMi * 10) / 10 : null),
        csvCell(done && it.avgMatch != null ? Math.round(it.avgMatch) : null),
      ].join(","),
    );
  }
  return lines.join("\r\n");
}

/** portfolio-2026-07-08.csv (local date — it names a download, not a record). */
export function portfolioCsvFilename(d: Date = new Date()): string {
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `portfolio-${d.getFullYear()}-${mm}-${dd}.csv`;
}

/* ── Totals (the footer row's math) ──────────────────────────────────────── */

export interface PortfolioTotals {
  /** Sum of mids across DONE items only. Null when nothing comped. */
  mid: number | null;
  low: number | null;
  high: number | null;
  done: number;
  errored: number;
  total: number;
}

export function portfolioTotals(items: PortfolioItem[]): PortfolioTotals {
  let mid = 0;
  let low = 0;
  let high = 0;
  let done = 0;
  let errored = 0;
  for (const it of items) {
    if (it.status === "error") errored++;
    if (it.status !== "done") continue;
    done++;
    mid += it.mid ?? 0;
    low += it.low ?? 0;
    high += it.high ?? 0;
  }
  return {
    mid: done ? mid : null,
    low: done ? low : null,
    high: done ? high : null,
    done,
    errored,
    total: items.length,
  };
}
