import "server-only";

import path from "node:path";
import {
  PROJECT_ROOT,
  OUTPUTS_DIR,
  spawnPython,
  parseBuilderResult,
} from "@/lib/cma/paths";
import { callWorker, workerEnabled, COMPBIRD_WORKER_URL } from "@/lib/cma/worker";
import { searchProperties, searchIndexAvailable } from "@/lib/cma/search-index";
import type { PropertyMatch } from "@/lib/cma/search-index";
import { createLogger } from "@/lib/utils/logger";

/**
 * compbird's engine adapter. The public `/api/compbird/*` routes are thin
 * wrappers over these helpers, which reuse the exact same MLS Bot bridge as the
 * host app's gated `/api/cma/*` routes (spawnPython + the warm worker). Keeping
 * the wiring here means compbird's public surface is isolated from — and never
 * mutates — the host's authenticated routes.
 *
 * Every helper resolves with `{ status, body }` and never throws, so the route
 * layer is a one-liner. `body` always carries `ok`.
 */
const log = createLogger("cma/engine");

export type Outcome<T> = { status: number; body: T };

const PROFILE_SPAWN_MS = 115_000;
const PROFILE_WORKER_MS = 10_000;
const PREVIEW_SPAWN_MS = 28_000;
// Warm-worker preview budget. Higher than the legacy fast preview because the
// worker /preview can run the full prepare_comps + AVM (+ optional hygiene) for
// exact PDF parity; still well under a cold spawn since the model stays resident.
const PREVIEW_WORKER_MS = 45_000;
const GENERATE_SPAWN_MS = 115_000;
const GENERATE_WORKER_MS = 113_000;
const SEARCH_SPAWN_MS = 7_000;
const MARKETS_SPAWN_MS = 18_000;

/**
 * OPT-IN comp-pool override for compbird. When COMPBIRD_LISTINGS_PARQUET points at
 * a parquet on the engine host, compbird's profile/preview/generate price off THAT
 * pool (the supplemental public-records sales source) instead of the MLS pool.
 * Unset (default) ⇒ compbird uses the MLS pool exactly as today. The host's gated
 * /api/cma path never sets this, so Ratifyly is unaffected. The engine reads it via
 * CMA_LISTINGS_PARQUET (warm worker: per-request from the body; spawn: process env).
 */
const COMPBIRD_LISTINGS_PARQUET = process.env.COMPBIRD_LISTINGS_PARQUET?.trim() || undefined;

export { OUTPUTS_DIR };
export type { PropertyMatch };

/* ── compbird spawn budget ───────────────────────────────────────────────────
 * The public compbird surface shares the host's global Python pool
 * (paths.ts SPAWN_MAX_CONCURRENCY, default 4). To keep headroom for the host's
 * authenticated /api/cma routes, compbird's heavy spawns pass through a tiny
 * local semaphore so they can never occupy more than COMPBIRD_SPAWN_BUDGET of
 * the global slots. This sits ON TOP of spawnPython's own admission control —
 * it only limits how many compbird spawns are in flight at once. The warm-worker
 * path (callWorker) is a separate process and is intentionally NOT gated here.
 */
const COMPBIRD_SPAWN_BUDGET = 2;
let compbirdActive = 0;
const compbirdWaiters: Array<() => void> = [];

function acquireCompbirdSlot(): Promise<void> {
  if (compbirdActive < COMPBIRD_SPAWN_BUDGET) {
    compbirdActive++;
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    compbirdWaiters.push(() => {
      compbirdActive++;
      resolve();
    });
  });
}

function releaseCompbirdSlot(): void {
  compbirdActive = Math.max(0, compbirdActive - 1);
  const next = compbirdWaiters.shift();
  if (next) next();
}

/**
 * Run a heavy compbird spawn under the compbird budget. Always releases in a
 * `finally`, so a throwing/rejecting body can never leak a permit (no deadlock).
 */
async function withCompbirdSlot<T>(fn: () => Promise<T>): Promise<T> {
  await acquireCompbirdSlot();
  try {
    return await fn();
  } finally {
    releaseCompbirdSlot();
  }
}

/* ── search ────────────────────────────────────────────────────────────────── */

const SEARCH_RUNNER = `
import json, math, os, sys, traceback
from pathlib import Path
ROOT = Path(os.environ["PROJECT_ROOT"])
sys.path.insert(0, str(ROOT / "src"))

def _clean(o):
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else o
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_clean(v) for v in o]
    return o

try:
    from mls_bot.analytics.property_lookup import search_properties
    q = os.environ.get("LOOKUP_Q", "")
    limit = int(os.environ.get("LOOKUP_LIMIT", "8"))
    matches = [_clean(m.to_dict()) for m in search_properties(q, limit=limit)]
    print("__JSON__" + json.dumps({"ok": True, "matches": matches}, allow_nan=False))
except Exception as e:
    print("__JSON__" + json.dumps({"ok": False, "error": str(e), "traceback": traceback.format_exc()}))
`;

export async function engineSearch(
  q: string,
  limit: number,
): Promise<Outcome<{ matches: PropertyMatch[]; cached?: boolean; error?: string }>> {
  const query = q.trim();
  if (query.length < 2) return { status: 200, body: { matches: [] } };
  const lim = Math.min(Math.max(limit || 8, 1), 20);

  // Fast path: in-Node SQLite/FTS5 index (no spawn).
  if (searchIndexAvailable()) {
    try {
      return { status: 200, body: { matches: searchProperties(query, lim) } };
    } catch (err) {
      log.error("Index search failed — falling back to Python", err, { q: query });
    }
  }

  const { stdout, stderr, code, timedOut } = await spawnPython(
    ["-c", SEARCH_RUNNER],
    { PROJECT_ROOT, LOOKUP_Q: query, LOOKUP_LIMIT: String(lim) },
    { timeoutMs: SEARCH_SPAWN_MS },
  );
  const parsed = parseBuilderResult<{ ok: boolean; matches?: PropertyMatch[]; error?: string }>(
    stdout,
  );
  if (!parsed || !parsed.ok) {
    log.error("Property search failed", undefined, {
      code,
      timedOut,
      error: parsed?.error,
      stderr: stderr.slice(0, 2000),
    });
    return {
      status: code === -2 ? 503 : 500,
      body: { matches: [], error: "Search failed." },
    };
  }
  return { status: 200, body: { matches: parsed.matches ?? [] } };
}

/* ── profile (full dossier) ──────────────────────────────────────────────────── */

export async function engineProfile<T extends { ok: boolean; error?: string }>(input: {
  address?: string;
  parcelId?: string;
}): Promise<Outcome<T | { ok: false; error: string }>> {
  const address = (input.address ?? "").trim();
  const parcelId = (input.parcelId ?? "").trim();
  if (!address && !parcelId) {
    return { status: 400, body: { ok: false, error: "Provide an address or parcelId." } };
  }

  let parsed: T | null = null;
  let stderr = "";
  let code = 0;
  let timedOut = false;

  if (workerEnabled()) {
    try {
      parsed = await callWorker<T>("/profile", { address, parcelId, listingsParquet: COMPBIRD_LISTINGS_PARQUET }, PROFILE_WORKER_MS, COMPBIRD_WORKER_URL);
    } catch (err) {
      log.warn("CMA worker unavailable — falling back to spawn", {
        error: err instanceof Error ? err.message : String(err),
      });
    }
  }

  if (!parsed) {
    const args = ["scripts/property_profile.py"];
    if (address) args.push(address);
    if (parcelId) args.push("--parcel", parcelId);
    const r = await withCompbirdSlot(() =>
      spawnPython(args, COMPBIRD_LISTINGS_PARQUET ? { CMA_LISTINGS_PARQUET: COMPBIRD_LISTINGS_PARQUET } : {}, { timeoutMs: PROFILE_SPAWN_MS }),
    );
    stderr = r.stderr;
    code = r.code;
    timedOut = r.timedOut ?? false;
    parsed = parseBuilderResult<T>(r.stdout);
  }

  if (!parsed) {
    log.error("Property profile produced no parseable result", undefined, {
      code,
      timedOut,
      stderr: stderr.slice(0, 4000),
    });
    if (code === -2) return { status: 503, body: { ok: false, error: "Server is busy. Please retry in a moment." } };
    return {
      status: 500,
      body: {
        ok: false,
        error: timedOut ? "Profile lookup timed out. Please try again." : "Profile lookup failed. Please try again.",
      },
    };
  }
  if (!parsed.ok) {
    log.error("Property profile reported failure", undefined, {
      error: parsed.error,
      stderr: stderr.slice(0, 4000),
    });
    return { status: 400, body: { ok: false, error: parsed.error || "Profile lookup failed." } };
  }
  return { status: 200, body: parsed };
}

/* ── preview (comp set + valuation, no PDF) ──────────────────────────────────── */

// Spawn fallback for when the warm worker is down. Calls the SAME build_preview
// (prepare_comps + _estimate_value) the worker /preview and the PDF generate use,
// so a fallback preview is byte-identical to the warm path — never the legacy
// raw-pick_comps math that diverged from the downloaded report.
const PREVIEW_RUNNER = `
import json, os, sys, traceback
from pathlib import Path
ROOT = Path(os.environ["PROJECT_ROOT"])
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
try:
    from build_cma import build_preview
    payload = json.loads(os.environ.get("PREVIEW_PAYLOAD", "{}"))
    out = build_preview(
        address=payload.get("address") or None,
        parcel_id=payload.get("parcelId") or None,
        comp_overrides=payload.get("forced") or None,
        excluded_comps=payload.get("excluded") or None,
        n_comps=int(payload.get("nComps") or 6),
        months_back=int(payload.get("months") or 24),
        ai_hygiene=bool(payload.get("aiHygiene", False)),
        subject_overrides=payload.get("subjectOverrides") or None,
    )
    print("__JSON__" + json.dumps(out, allow_nan=False, default=str))
except Exception as e:
    print("__JSON__" + json.dumps({"ok": False, "error": str(e), "traceback": traceback.format_exc()}))
`;

export async function enginePreview<T extends { ok: boolean; error?: string }>(payload: {
  address?: string;
  parcelId?: string;
  months?: number;
  nComps?: number;
  excluded?: string[];
  forced?: string[];
  /**
   * Full-accuracy pipeline (AVM + Haiku hygiene) for EXACT preview==PDF parity.
   * Defaults OFF here so the public/anonymous studio stays fast + free; the
   * authenticated builder sets it true before the value is committed/downloaded.
   */
  aiHygiene?: boolean;
  /**
   * Agent CMA control: engine-shaped (snake-key) subject-fact overrides — see
   * toEngineOverrides() in @/lib/cma/overrides. Additive: absent ⇒ subject
   * resolved from records unchanged. Travels on the wire under `subjectOverrides`.
   */
  subjectOverrides?: Record<string, unknown>;
}): Promise<Outcome<T | { ok: false; error: string }>> {
  const address = (payload.address ?? "").trim();
  const parcelId = (payload.parcelId ?? "").trim();
  if (!address && !parcelId) {
    return { status: 400, body: { ok: false, error: "Provide an address or parcelId." } };
  }

  // Warm-worker first: /preview runs the SAME prepare_comps + _estimate_value as
  // /generate (via build_preview), so the tuned number matches the downloaded PDF
  // and we skip the ~2s cold spawn + AVM re-import. Falls back to the spawn runner
  // (same build_preview) on any worker failure, so behavior is identical either way.
  // SERVER-decided by the route from the authenticated session: an authenticated
  // builder gets full AVM + LLM hygiene; anonymous gets AVM-on + LLM-off (no spend,
  // and on-screen == PDF within each auth state). build_preview runs the AVM
  // regardless; this flag gates ONLY the LLM pass. `=== true` so a missing value is
  // treated as anonymous — the client can never flip it on.
  const aiHygiene = payload.aiHygiene === true;
  if (workerEnabled()) {
    try {
      const parsed = await callWorker<T & { ok: boolean }>(
        "/preview",
        { address, parcelId, months: payload.months, nComps: payload.nComps, excluded: payload.excluded, forced: payload.forced, aiHygiene, subjectOverrides: payload.subjectOverrides, listingsParquet: COMPBIRD_LISTINGS_PARQUET },
        PREVIEW_WORKER_MS,
        COMPBIRD_WORKER_URL,
      );
      if (parsed?.ok) return { status: 200, body: parsed };
      if (parsed && !parsed.ok)
        return { status: 400, body: parsed as { ok: false; error: string } };
    } catch (err) {
      log.warn("CMA worker /preview unavailable — falling back to spawn", {
        error: err instanceof Error ? err.message : String(err),
      });
    }
  }

  const { stdout, stderr, code, timedOut } = await withCompbirdSlot(() =>
    spawnPython(
      ["-c", PREVIEW_RUNNER],
      { PROJECT_ROOT, PREVIEW_PAYLOAD: JSON.stringify({ address, parcelId, ...payload, aiHygiene }), ...(COMPBIRD_LISTINGS_PARQUET ? { CMA_LISTINGS_PARQUET: COMPBIRD_LISTINGS_PARQUET } : {}) },
      { timeoutMs: PREVIEW_SPAWN_MS },
    ),
  );
  const parsed = parseBuilderResult<T>(stdout);
  if (!parsed) {
    log.error("CMA preview produced no parseable result", undefined, { code, timedOut, stderr: stderr.slice(0, 4000) });
    if (code === -2) return { status: 503, body: { ok: false, error: "Server is busy. Please retry in a moment." } };
    return { status: 500, body: { ok: false, error: timedOut ? "Preview timed out. Please try again." : "Preview failed. Please try again." } };
  }
  if (!parsed.ok) {
    log.error("CMA preview reported failure", undefined, { error: parsed.error, stderr: stderr.slice(0, 4000) });
    return { status: 400, body: { ok: false, error: parsed.error || "Preview failed." } };
  }
  return { status: 200, body: parsed };
}

/* ── generate (render branded PDF) ───────────────────────────────────────────── */

const GENERATE_RUNNER = `
import json, os, sys, traceback
from pathlib import Path
ROOT = Path(os.environ["PROJECT_ROOT"])
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
try:
    from build_cma import build_cma
    payload = json.loads(os.environ.get("CMA_PAYLOAD", "{}"))
    os.environ.pop("CMA_SKIP_AVM", None)  # AVM ON (match the warm worker + preview) so spawn-fallback value == warm value
    r = build_cma(
        address=payload.get("address") or None,
        parcel_id=payload.get("parcelId") or None,
        brand_name=payload.get("brand") or "general",
        agent_name=payload.get("agent") or None,
        comp_overrides=payload.get("comps") or None,
        excluded_comps=payload.get("excluded") or None,
        n_comps=int(payload.get("nComps") or 6),
        months_back=int(payload.get("months") or 24),
        allow_multi_page=bool(payload.get("allowMultiPage")),
        ai_hygiene=bool(payload.get("aiHygiene", True)),
        subject_overrides=payload.get("subjectOverrides") or None,
        report_config=payload.get("reportConfig") or None,
    )
    print("__JSON__" + json.dumps({
        "ok": True, "subject_address": r.subject_address, "estimated_value": r.estimated_value,
        "value_low": r.value_low, "value_high": r.value_high, "comp_count": r.comp_count,
        "pages": r.pages, "elapsed_seconds": r.elapsed_seconds, "autofit_attempts": r.autofit_attempts,
        "html_path": str(r.html_path), "pdf_path": str(r.pdf_path),
    }))
except Exception as e:
    print("__JSON__" + json.dumps({"ok": False, "error": str(e), "traceback": traceback.format_exc()}))
`;

interface BuilderOutput {
  ok: boolean;
  subject_address?: string;
  estimated_value?: number;
  value_low?: number;
  value_high?: number;
  comp_count?: number;
  pages?: number;
  elapsed_seconds?: number;
  autofit_attempts?: number;
  html_path?: string;
  pdf_path?: string;
  error?: string;
}

export interface GenerateBody {
  ok: boolean;
  subject?: string;
  valueLow?: number;
  valueMid?: number;
  valueHigh?: number;
  compCount?: number;
  pages?: number;
  elapsedSeconds?: number;
  autofitAttempts?: number;
  pdfName?: string;
  htmlName?: string;
  error?: string;
}

// Public-surface brands the generate route will honor (anti-spoof allowlist).
// Neutral "general" is the de-branded default; "compbird" stays available as an
// explicit branded option. Server-side only — never trust a client brand string.
const PUBLIC_BRAND_ALLOWLIST = new Set(["general", "compbird"]);

export async function engineGenerate(payload: {
  address?: string;
  parcelId?: string;
  brand?: string;
  agent?: string;
  comps?: string[];
  excluded?: string[];
  months?: number;
  nComps?: number;
  allowMultiPage?: boolean;
  aiHygiene?: boolean;
  /**
   * Agent CMA control: engine-shaped (snake-key) subject-fact overrides — see
   * toEngineOverrides() in @/lib/cma/overrides. Additive; travels under the
   * `subjectOverrides` wire key into build_cma(subject_overrides=...).
   */
  subjectOverrides?: Record<string, unknown>;
  /**
   * Report composition + narrative overrides ({sections?, execText?,
   * strategyText?}) — see sanitizeReportConfig() in @/lib/cma/overrides. Travels
   * under the `reportConfig` wire key into build_cma(report_config=...). The
   * statutory disclaimer is NOT part of this and is engine-locked.
   */
  reportConfig?: unknown;
}): Promise<Outcome<GenerateBody>> {
  const address = (payload.address ?? "").trim();
  const parcelId = (payload.parcelId ?? "").trim();
  if (!address && !parcelId) {
    return { status: 400, body: { ok: false, error: "Provide an address or parcelId." } };
  }
  // De-branded by default. The public surface never trusts a client-supplied
  // brand (anti-spoof) — only the vetted allowlist is honored, defaulting to the
  // neutral "general" template so reports are general CMA documents, not an
  // internal brand's letterhead.
  const brand = PUBLIC_BRAND_ALLOWLIST.has(payload.brand ?? "") ? payload.brand! : "general";
  // aiHygiene is SERVER-decided by the route (authed → full hygiene; anon → off).
  // `=== true` forces an explicit boolean so a missing/absent value can never let
  // the GENERATE_RUNNER/worker default (True) spend LLM on an anonymous caller.
  // The trailing key wins over any client-supplied aiHygiene in ...payload.
  // Drop the legacy top-level `subjectSqft` lever on the compbird surface: sqft
  // correction goes through `subjectOverrides.sqft` — the SINGLE path that is
  // auth-gated, clamped (OVERRIDE_BOUNDS), audited, AND disclosed. Setting it
  // undefined here strips any raw-client `subjectSqft` from the worker/spawn body,
  // so it can never re-value a report off the gated/disclosed path (JSON.stringify
  // omits undefined keys; the shared worker still honors subject_sqft for the host).
  const body = {
    ...payload,
    address,
    parcelId,
    brand,
    aiHygiene: payload.aiHygiene === true,
    subjectSqft: undefined,
    listingsParquet: COMPBIRD_LISTINGS_PARQUET,
  };

  let parsed: BuilderOutput | null = null;
  let stderr = "";
  let code = 0;
  let timedOut = false;

  if (workerEnabled()) {
    try {
      parsed = await callWorker<BuilderOutput>("/generate", body, GENERATE_WORKER_MS, COMPBIRD_WORKER_URL);
    } catch (err) {
      log.warn("CMA worker unavailable — falling back to spawn", {
        error: err instanceof Error ? err.message : String(err),
      });
    }
  }

  if (!parsed) {
    const r = await withCompbirdSlot(() =>
      spawnPython(
        ["-c", GENERATE_RUNNER],
        { PROJECT_ROOT, CMA_PAYLOAD: JSON.stringify(body), ...(COMPBIRD_LISTINGS_PARQUET ? { CMA_LISTINGS_PARQUET: COMPBIRD_LISTINGS_PARQUET } : {}) },
        { timeoutMs: GENERATE_SPAWN_MS },
      ),
    );
    stderr = r.stderr;
    code = r.code;
    timedOut = r.timedOut ?? false;
    parsed = parseBuilderResult<BuilderOutput>(r.stdout);
  }

  if (!parsed) {
    log.error("CMA generate produced no parseable result", undefined, { code, timedOut, stderr: stderr.slice(0, 4000) });
    if (code === -2) return { status: 503, body: { ok: false, error: "Server is busy. Please retry in a moment." } };
    return {
      status: 500,
      body: { ok: false, error: timedOut ? "Report generation timed out. Please try again." : "Report generation failed. Please try again." },
    };
  }
  if (!parsed.ok) {
    log.error("CMA builder reported failure", undefined, { error: parsed.error, stderr: stderr.slice(0, 4000) });
    return { status: 500, body: { ok: false, error: "Report generation failed. Please try again." } };
  }

  return {
    status: 200,
    body: {
      ok: true,
      subject: parsed.subject_address,
      valueLow: parsed.value_low,
      valueMid: parsed.estimated_value,
      valueHigh: parsed.value_high,
      compCount: parsed.comp_count,
      pages: parsed.pages,
      elapsedSeconds: parsed.elapsed_seconds,
      autofitAttempts: parsed.autofit_attempts,
      pdfName: parsed.pdf_path ? path.basename(parsed.pdf_path) : undefined,
      htmlName: parsed.html_path ? path.basename(parsed.html_path) : undefined,
    },
  };
}

/* ── markets (live neighborhood tear-sheets for the landing) ─────────────────── */

/**
 * One live neighborhood card, mirroring `NeighborhoodMarket` in
 * src/lib/compbird/types.ts (the RUNNER emits these field names verbatim so the
 * route can hand the array straight to the client).
 */
export interface EngineMarket {
  name: string;
  area: string;
  medianPrice: number;
  ppsf: number;
  ppsfTrendPct: number;
  medianDom: number;
  monthsOfInventory: number;
  soldCount: number;
  activeCount: number;
  trend: number[];
  note: string;
}

/**
 * Aggregates the top New River Valley neighborhoods (by recent sold count) into
 * the landing's market-card shape, computed from the SAME slim
 * `data/mls_lookup.parquet` the per-subject `_market_context` query reads. The
 * filters (RE_1 class, Closed status, positive sold price, 12-month window) and
 * the median-$/sqft / DOM / months-of-inventory / split-half trend math all
 * mirror property_profile.py's `_market_context`, but scoped per-neighborhood
 * and ranked instead of resolved against a single subject.
 *
 * The runner NEVER raises: on any failure (missing parquet, DuckDB error, no
 * rows) it prints `{ok: true, markets: []}` so the landing keeps its sample.
 */
const MARKETS_RUNNER = `
import json, math, os, sys, traceback
from pathlib import Path
ROOT = Path(os.environ["PROJECT_ROOT"])
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

WINDOW_MONTHS = 12          # same window as _market_context
MIN_SOLD = 6                # only surface neighborhoods with a credible sample
MAX_CARDS = 6
CLASS = "RE_1"
# Subdivision placeholders the feed uses for "no real subdivision" — never a card.
PLACEHOLDERS = ("", "NONE", "OTHER", "N/A", "NA", "UNKNOWN", "TBD")

def _f(v):
    try:
        if v is None: return None
        v = float(v)
        return None if (math.isnan(v) or math.isinf(v)) else v
    except Exception:
        return None

def _emit(markets):
    print("__JSON__" + json.dumps({"ok": True, "markets": markets}, allow_nan=False))

def _trend_series(con, scope_clause):
    """12-point oldest->newest price series for the sparkline. Per-month median,
    then forward/back-filled and lightly smoothed toward the overall median so a
    thin month doesn't spike the line. Cosmetic only — headline figures are the
    real aggregates."""
    try:
        rows = con.execute(
            f"""WITH sold AS (
                    SELECT TRY_CAST(sold_price AS DOUBLE) sp,
                           11 - date_diff('month', date_trunc('month', close_date),
                                          date_trunc('month', CURRENT_DATE)) AS idx
                    FROM l
                    WHERE _class = '{CLASS}' AND status_category = 'Closed'
                      AND TRY_CAST(sold_price AS DOUBLE) > 0
                      AND close_date >= (CURRENT_DATE - INTERVAL '{WINDOW_MONTHS} months')
                      AND {scope_clause}
                )
                SELECT idx, MEDIAN(sp) m FROM sold
                WHERE idx BETWEEN 0 AND 11 GROUP BY idx ORDER BY idx"""
        ).fetchall()
    except Exception:
        return None
    by_idx = {int(i): _f(m) for i, m in rows if _f(m) is not None}
    if not by_idx:
        return None
    vals = list(by_idx.values())
    overall = sorted(vals)[len(vals) // 2]
    # Forward-fill gaps; seed the head from the first known value.
    series, last = [], None
    for i in range(12):
        v = by_idx.get(i)
        if v is None:
            v = last if last is not None else overall
        series.append(v)
        last = v
    # Light smoothing (3-pt moving avg, ends held) so the line reads clean.
    sm = []
    for i in range(12):
        lo, hi = max(0, i - 1), min(11, i + 1)
        win = series[lo:hi + 1]
        sm.append(round(sum(win) / len(win)))
    return sm

def _note(scope_label, med_dom, moi, trend_pct, n_sold):
    bits = []
    if moi is not None:
        if moi < 3:
            bits.append("tight supply favors sellers")
        elif moi < 6:
            bits.append("supply and demand are balanced")
        else:
            bits.append("ample supply favors buyers")
    if med_dom is not None:
        if med_dom <= 14:
            bits.append("homes clear in under two weeks")
        elif med_dom <= 30:
            bits.append(f"a typical sale takes about {int(med_dom)} days")
        else:
            bits.append(f"listings sit ~{int(med_dom)} days before closing")
    if trend_pct is not None and abs(trend_pct) >= 1.0:
        bits.append(f"$/sqft is {'up' if trend_pct > 0 else 'down'} {abs(trend_pct):.1f}% year over year")
    head = "; ".join(bits[:2]) if bits else f"{int(n_sold)} closings in the trailing year"
    return head[:1].upper() + head[1:] + "."

try:
    import duckdb
    parquet = ROOT / "data" / "mls_lookup.parquet"
    if not parquet.exists():
        _emit([]); sys.exit(0)

    con = duckdb.connect(":memory:")
    con.execute(f"CREATE VIEW l AS SELECT * FROM read_parquet('{parquet.as_posix()}')")

    placeholders_sql = ", ".join("'" + p + "'" for p in PLACEHOLDERS)
    # Top neighborhoods by recent sold count. Group on the raw subdivision but
    # drop feed placeholders so we only surface real, named neighborhoods.
    ranked = con.execute(
        f"""WITH sold AS (
                SELECT subdivision, city, county,
                       TRY_CAST(sold_price AS DOUBLE) sp,
                       TRY_CAST(sqft AS DOUBLE) sf,
                       TRY_CAST(feed_dom AS INT) dom
                FROM l
                WHERE _class = '{CLASS}' AND status_category = 'Closed'
                  AND TRY_CAST(sold_price AS DOUBLE) > 0
                  AND close_date >= (CURRENT_DATE - INTERVAL '{WINDOW_MONTHS} months')
                  AND subdivision IS NOT NULL
                  AND UPPER(TRIM(subdivision)) NOT IN ({placeholders_sql})
            )
            SELECT subdivision,
                   ANY_VALUE(city) city, ANY_VALUE(county) county,
                   COUNT(*) n_sold,
                   MEDIAN(sp) med_price,
                   MEDIAN(CASE WHEN sf > 0 THEN sp / sf END) med_ppsf,
                   MEDIAN(dom) med_dom
            FROM sold
            GROUP BY subdivision
            HAVING COUNT(*) >= {MIN_SOLD}
            ORDER BY n_sold DESC
            LIMIT {MAX_CARDS}"""
    ).fetchall()

    markets = []
    for sub, city, county, n_sold, med_price, med_ppsf, med_dom in ranked:
        sub_sql = str(sub).replace("'", "''")
        scope_clause = f"subdivision = '{sub_sql}'"

        active = con.execute(
            f"SELECT COUNT(*) FROM l WHERE _class = '{CLASS}' "
            f"AND status_category = 'Active' AND {scope_clause}"
        ).fetchone()
        active_count = int(active[0]) if active and active[0] is not None else 0

        n = int(n_sold)
        moi = None
        if n > 0:
            per_month = n / float(WINDOW_MONTHS)
            if per_month > 0:
                moi = active_count / per_month

        # Split-half $/sqft trend — identical idea to _market_context.
        trend_pct = None
        try:
            halves = con.execute(
                f"""WITH sold AS (
                        SELECT TRY_CAST(sold_price AS DOUBLE) sp,
                               TRY_CAST(sqft AS DOUBLE) sf, close_date
                        FROM l
                        WHERE _class = '{CLASS}' AND status_category = 'Closed'
                          AND TRY_CAST(sold_price AS DOUBLE) > 0
                          AND TRY_CAST(sqft AS DOUBLE) > 0
                          AND close_date >= (CURRENT_DATE - INTERVAL '{WINDOW_MONTHS} months')
                          AND {scope_clause}
                    ),
                    tagged AS (
                        SELECT sp / sf AS ppsf,
                               CASE WHEN close_date >=
                                    (CURRENT_DATE - INTERVAL '{WINDOW_MONTHS // 2} months')
                                    THEN 'recent' ELSE 'older' END AS half
                        FROM sold
                    )
                    SELECT half, MEDIAN(ppsf) med, COUNT(*) c FROM tagged GROUP BY half"""
            ).fetchall()
            by_half = {h: (m, c) for h, m, c in halves}
            recent, older = by_half.get("recent"), by_half.get("older")
            if recent and older and recent[1] >= 3 and older[1] >= 3 and older[0]:
                trend_pct = (recent[0] - older[0]) / older[0] * 100.0
        except Exception:
            trend_pct = None

        trend = _trend_series(con, scope_clause)
        med_price_f = _f(med_price)
        med_ppsf_f = _f(med_ppsf)
        if med_price_f is None or med_ppsf_f is None:
            continue  # a card with no headline is useless — skip it
        if not trend:
            trend = [round(med_price_f)] * 12

        med_dom_i = int(med_dom) if med_dom is not None else 0
        trend_pct_r = round(trend_pct, 1) if trend_pct is not None else 0.0
        moi_r = round(moi, 1) if moi is not None else 0.0
        area = ", ".join([str(x) for x in (city, (str(county) + " County") if county else None) if x]) or "New River Valley, VA"
        markets.append({
            "name": str(sub),
            "area": area,
            "medianPrice": int(round(med_price_f)),
            "ppsf": int(round(med_ppsf_f)),
            "ppsfTrendPct": trend_pct_r,
            "medianDom": med_dom_i,
            "monthsOfInventory": moi_r,
            "soldCount": n,
            "activeCount": active_count,
            "trend": trend,
            "note": _note(str(sub), med_dom_i, moi, trend_pct, n),
        })

    _emit(markets)
except Exception as e:
    # Never crash the landing — fall back to the sample by returning empty.
    sys.stderr.write(traceback.format_exc())
    _emit([])
`;

// Neighborhood aggregates change slowly (a closing here and there), but the
// landing fetches this on every page load and each miss is an ~18s DuckDB scan.
// Cache the result process-wide and coalesce concurrent misses into ONE spawn so
// a traffic spike can't fan out into a pile of parquet reads.
const MARKETS_TTL_MS = 30 * 60_000; // serve a good result for 30 min
const MARKETS_EMPTY_TTL_MS = 60_000; // retry an empty/failed result sooner
let _marketsCache: { at: number; body: { markets: EngineMarket[] } } | null = null;
let _marketsInflight: Promise<Outcome<{ markets: EngineMarket[] }>> | null = null;

async function computeMarkets(): Promise<Outcome<{ markets: EngineMarket[] }>> {
  const { stdout, stderr, code, timedOut } = await withCompbirdSlot(() =>
    spawnPython(
      ["-c", MARKETS_RUNNER],
      { PROJECT_ROOT },
      { timeoutMs: MARKETS_SPAWN_MS },
    ),
  );
  const parsed = parseBuilderResult<{ ok: boolean; markets?: EngineMarket[] }>(stdout);
  if (!parsed || !parsed.ok || !Array.isArray(parsed.markets)) {
    // Soft-fail: an empty array makes the client keep its built-in sample.
    log.warn("Live markets unavailable — landing will use sample", {
      code,
      timedOut,
      stderr: stderr.slice(0, 1000),
    });
    const body = { markets: [] as EngineMarket[] };
    _marketsCache = { at: Date.now(), body };
    return { status: 200, body };
  }
  const body = { markets: parsed.markets };
  _marketsCache = { at: Date.now(), body };
  return { status: 200, body };
}

export async function engineMarkets(): Promise<Outcome<{ markets: EngineMarket[] }>> {
  if (_marketsCache) {
    const ttl = _marketsCache.body.markets.length > 0 ? MARKETS_TTL_MS : MARKETS_EMPTY_TTL_MS;
    if (Date.now() - _marketsCache.at < ttl) {
      return { status: 200, body: _marketsCache.body };
    }
  }
  // Coalesce concurrent cache-misses into a single in-flight computation.
  if (!_marketsInflight) {
    _marketsInflight = computeMarkets().finally(() => {
      _marketsInflight = null;
    });
  }
  return _marketsInflight;
}
