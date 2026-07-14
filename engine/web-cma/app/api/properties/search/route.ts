import { NextResponse } from "next/server";
import { spawn } from "node:child_process";
import path from "node:path";
import { PROJECT_ROOT, PYTHON_SRC } from "@/lib/paths";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Typeahead queries run against the slim Parquet lookup files (~10 MB total)
// so they complete well under a second. The 8-second cap is a safety net.
export const maxDuration = 8;

interface PropertyMatch {
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

interface RunnerResult {
  ok: boolean;
  matches?: PropertyMatch[];
  error?: string;
}

/**
 * Tiny in-process LRU so repeated keystrokes at the same prefix don't
 * re-spawn Python. Keyed by ``q|limit``. Capacity 64 entries, TTL 60 s.
 */
const _cache = new Map<string, { at: number; matches: PropertyMatch[] }>();
const CACHE_TTL_MS = 60_000;
const CACHE_MAX = 64;

function cacheGet(key: string): PropertyMatch[] | undefined {
  const hit = _cache.get(key);
  if (!hit) return undefined;
  if (Date.now() - hit.at > CACHE_TTL_MS) {
    _cache.delete(key);
    return undefined;
  }
  // refresh LRU position
  _cache.delete(key);
  _cache.set(key, hit);
  return hit.matches;
}

function cacheSet(key: string, matches: PropertyMatch[]) {
  _cache.set(key, { at: Date.now(), matches });
  if (_cache.size > CACHE_MAX) {
    const oldest = _cache.keys().next().value;
    if (oldest !== undefined) _cache.delete(oldest);
  }
}

function runPython(args: string[], extraEnv: Record<string, string> = {}): Promise<{
  stdout: string;
  stderr: string;
  code: number;
}> {
  return new Promise((resolve) => {
    const env = {
      ...process.env,
      PYTHONPATH: process.env.PYTHONPATH
        ? `${PYTHON_SRC}${path.delimiter}${process.env.PYTHONPATH}`
        : PYTHON_SRC,
      PYTHONIOENCODING: "utf-8",
      ...extraEnv,
    };
    const proc = spawn("python", ["-X", "utf8", ...args], {
      cwd: PROJECT_ROOT,
      env,
      shell: false,
    });
    let stdout = "";
    let stderr = "";
    proc.stdout.on("data", (b) => {
      stdout += b.toString();
    });
    proc.stderr.on("data", (b) => {
      stderr += b.toString();
    });
    proc.on("close", (code) => resolve({ stdout, stderr, code: code ?? -1 }));
    proc.on("error", (err) => resolve({ stdout, stderr: stderr + String(err), code: -1 }));
  });
}

const RUNNER = `
import json, math, os, sys, traceback
from pathlib import Path
ROOT = Path(os.environ["PROJECT_ROOT"])
sys.path.insert(0, str(ROOT / "src"))

def _clean(o):
    """Replace NaN/inf with None so json.dumps emits valid JSON."""
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

    # Layer 2 — natural-language search. Only fires when the query reads like
    # prose (not an address) AND an API key is configured; otherwise the plain
    # token search runs. Keeps the LLM off the ordinary address typeahead.
    nl_used = False
    nl_summary = []
    matches = []
    try:
        from mls_bot.analytics.nl_query import looks_like_prose, search_by_nl
        if looks_like_prose(q):
            nl = search_by_nl(q, limit=limit)
            if nl and nl.get("matches"):
                nl_used = True
                nl_summary = nl.get("summary", [])
                matches = [_clean(m) for m in nl["matches"]]
    except Exception:
        pass

    if not matches:
        matches = [_clean(m.to_dict()) for m in search_properties(q, limit=limit)]

    print("__JSON__" + json.dumps({
        "ok": True, "matches": matches,
        "nl_used": nl_used, "nl_summary": nl_summary,
    }, allow_nan=False))
except Exception as e:
    print("__JSON__" + json.dumps({
        "ok": False,
        "error": str(e),
        "traceback": traceback.format_exc(),
    }))
`;

function parseResult(stdout: string): RunnerResult | null {
  const marker = "__JSON__";
  const idx = stdout.lastIndexOf(marker);
  if (idx === -1) return null;
  try {
    return JSON.parse(stdout.slice(idx + marker.length).trim());
  } catch {
    return null;
  }
}

export async function GET(req: Request) {
  const url = new URL(req.url);
  const q = (url.searchParams.get("q") ?? "").trim();
  const limit = Math.min(
    Math.max(parseInt(url.searchParams.get("limit") ?? "8", 10) || 8, 1),
    20
  );
  if (q.length < 2) {
    return NextResponse.json({ matches: [] });
  }

  const cacheKey = `${q.toLowerCase()}|${limit}`;
  const cached = cacheGet(cacheKey);
  if (cached) {
    return NextResponse.json({ matches: cached, cached: true });
  }

  const { stdout, stderr, code } = await runPython(["-c", RUNNER], {
    PROJECT_ROOT,
    LOOKUP_Q: q,
    LOOKUP_LIMIT: String(limit),
  });
  const parsed = parseResult(stdout);
  if (!parsed || !parsed.ok) {
    return NextResponse.json(
      {
        matches: [],
        error: parsed?.error || `Python exited ${code}`,
        stderr: stderr.slice(0, 2000),
      },
      { status: 500 }
    );
  }
  cacheSet(cacheKey, parsed.matches ?? []);
  return NextResponse.json({ matches: parsed.matches ?? [] });
}
