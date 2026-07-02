import "server-only";

import path from "node:path";
import Database from "better-sqlite3";

import { PROJECT_ROOT } from "@/lib/cma/paths";
import { createLogger } from "@/lib/utils/logger";

const log = createLogger("cma/search-index");

/**
 * In-process address typeahead, served from a prebuilt SQLite + FTS5 index
 * (data/search_index.sqlite, built by MLS Bot/scripts/build_search_index.py).
 * Replaces the old per-keystroke `python -c` cold-spawn (~2.4s) with a sub-2ms
 * in-Node query. If the index file is missing, callers fall back to Python.
 */

export interface PropertyMatch {
  source: "mls" | "parcel";
  address: string;
  city: string;
  county: string;
  parcel_id: string;
  acres?: number | null;
  sqft?: number | null;
  year_built?: number | null;
  bedrooms?: number | null;
  full_baths?: number | null;
  half_baths?: number | null;
  owner?: string | null;
  subdivision?: string | null;
  last_sale_price?: number | null;
  last_sale_date?: string | null;
  status: string;
  list_price?: number | null;
  list_date?: string | null;
  listing_id?: string | null;
}

type DbHandle = {
  db: Database.Database;
  mlsStmt: Database.Statement;
  parcelStmt: Database.Statement;
} | null;

// Cache on globalThis so a dev hot-reload reuses the open read-only handle.
const g = globalThis as unknown as { __cmaSearchIndex?: DbHandle };

const COLS = `p.source, p.address, p.city, p.county, p.parcel_id, p.acres, p.sqft,
       p.year_built, p.bedrooms, p.full_baths, p.half_baths, p.owner,
       p.subdivision, p.last_sale_price, p.last_sale_date, p.status,
       p.list_price, p.list_date, p.listing_id`;

// Primary query: MLS-only FTS (~44k rows) — single-digit ms even for a bare
// common city/street token, and surfaces real listings (with lat/lng) first.
const SELECT_MLS = `
SELECT ${COLS}
FROM mls_fts f JOIN properties p ON p.id = f.rowid
WHERE mls_fts MATCH @match
ORDER BY p.rank0 ASC, bm25(mls_fts) ASC
LIMIT @limit`;

// Supplement: parcels only (rank0 = 4), from the full index. Runs only when MLS
// returns fewer than the requested limit (sparse / no-MLS-coverage areas).
const SELECT_PARCEL = `
SELECT ${COLS}
FROM properties_fts f JOIN properties p ON p.id = f.rowid
WHERE properties_fts MATCH @match AND p.rank0 = 4
ORDER BY bm25(properties_fts) ASC
LIMIT @limit`;

function indexPath(): string {
  return (
    process.env.SEARCH_INDEX_PATH?.trim() ||
    path.join(PROJECT_ROOT, "data", "search_index.sqlite")
  );
}

/** Open (once) the read-only index. Returns null if the file isn't built yet. */
function handle(): DbHandle {
  if (g.__cmaSearchIndex !== undefined) return g.__cmaSearchIndex;
  try {
    const db = new Database(indexPath(), { readonly: true, fileMustExist: true });
    db.pragma("query_only = true");
    db.pragma("mmap_size = 268435456"); // 256MB mmap → reads served from page cache
    g.__cmaSearchIndex = {
      db,
      mlsStmt: db.prepare(SELECT_MLS),
      parcelStmt: db.prepare(SELECT_PARCEL),
    };
    log.info("Search index opened", { path: indexPath() });
  } catch (err) {
    log.warn("Search index unavailable — search will fall back to Python", {
      error: err instanceof Error ? err.message : String(err),
      path: indexPath(),
    });
    g.__cmaSearchIndex = null;
  }
  return g.__cmaSearchIndex ?? null;
}

export function searchIndexAvailable(): boolean {
  return handle() !== null;
}

/** Build an FTS5 prefix MATCH from free text: alnum tokens (>=2 chars) + `*`. */
function toMatch(q: string): string | null {
  const toks = q
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .split(" ")
    .filter((t) => t.length >= 2);
  if (toks.length === 0) return null;
  return toks.map((t) => `${t}*`).join(" ");
}

/**
 * Typeahead search. Returns up to `limit` matches, MLS-first then parcels,
 * deduped by address (relisted MLS rows + MLS/parcel overlaps collapse to one).
 * Throws if the index is unavailable so the route can fall back to Python.
 */
export function searchProperties(q: string, limit = 8): PropertyMatch[] {
  const h = handle();
  if (!h) throw new Error("search index unavailable");
  const match = toMatch(q);
  if (!match) return [];

  const over = Math.min(limit * 4, 64);
  const seen = new Set<string>();
  const out: PropertyMatch[] = [];
  const take = (rows: PropertyMatch[]) => {
    for (const r of rows) {
      // Dedupe relisted MLS rows + MLS/parcel overlaps by address+county.
      const key = `${(r.address ?? "").toLowerCase().trim()}|${(r.county ?? "").toLowerCase()}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(r);
      if (out.length >= limit) return;
    }
  };

  // MLS-first (fast): fills the dropdown instantly anywhere there are listings.
  take(h.mlsStmt.all({ match, limit: over }) as PropertyMatch[]);

  // Supplement with parcels only when MLS didn't fill the limit (sparse / no-MLS
  // areas). Skipped entirely in the common case, so the big parcel index never
  // touches the hot path for a city/street with listings.
  if (out.length < limit) {
    take(h.parcelStmt.all({ match, limit: over }) as PropertyMatch[]);
  }
  return out;
}
