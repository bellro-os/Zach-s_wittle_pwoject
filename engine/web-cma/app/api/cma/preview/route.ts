import { NextResponse } from "next/server";
import { spawn } from "node:child_process";
import path from "node:path";
import { PROJECT_ROOT, PYTHON_SRC } from "@/lib/paths";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Preview runs resolve_subject + pick_comps + _estimate_value only — no PDF
// rendering, no headless Chrome. Should finish in 3-6 s on a warm cache.
export const maxDuration = 30;

interface PreviewRequest {
  address?: string;
  parcelId?: string;
  months?: number;
  nComps?: number;
  excluded?: string[];
  forced?: string[];
}

interface PreviewResult {
  ok: boolean;
  subject?: Record<string, unknown>;
  comps?: Array<Record<string, unknown>>;
  valuation?: {
    low: number;
    mid: number;
    high: number;
    ppsf: number;
    divergence_pct: number;
    methods: Array<{
      name: string;
      value: number | null;
      low: number | null;
      high: number | null;
      rationale: string;
    }>;
  };
  elapsed_seconds?: number;
  error?: string;
  stderr?: string;
}

function runPython(
  args: string[],
  extraEnv: Record<string, string> = {}
): Promise<{ stdout: string; stderr: string; code: number }> {
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
    proc.on("error", (err) =>
      resolve({ stdout, stderr: stderr + String(err), code: -1 })
    );
  });
}

/**
 * Runner script — invokes resolve_subject + pick_comps + _estimate_value and
 * prints a single JSON line. The payload is read from PREVIEW_PAYLOAD env
 * var so we never have to interpolate JS literals into Python source
 * (same pattern as the generate route).
 */
const RUNNER = `
import json, math, os, sys, time, traceback
from pathlib import Path
ROOT = Path(os.environ["PROJECT_ROOT"])
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

def _clean(o):
    """NaN/inf -> None so json.dumps(allow_nan=False) succeeds."""
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else o
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_clean(v) for v in o]
    return o

try:
    from build_cma import _estimate_value, _num, _round_to_5k
    from mls_bot.analytics.property_lookup import resolve_subject
    from mls_bot.analytics.cma_compset import pick_comps

    payload = json.loads(os.environ.get("PREVIEW_PAYLOAD", "{}"))
    address = payload.get("address") or None
    parcel_id = payload.get("parcelId") or None
    months = int(payload.get("months") or 24)
    n = int(payload.get("nComps") or 6)
    excluded = payload.get("excluded") or None
    forced = payload.get("forced") or None

    t0 = time.perf_counter()
    subject = resolve_subject(address=address, parcel_id=parcel_id)
    if subject is None:
        print("__JSON__" + json.dumps({
            "ok": False,
            "error": "Could not locate subject in MLS or parcel data.",
        }))
        sys.exit(0)
    # Numeric coercion — same as build_cma.
    for k in ("sqft","acres","list_price","original_list_price","sold_price",
              "bedrooms","full_baths","half_baths","year_built","feed_dom",
              "latitude","longitude"):
        v = _num(subject.get(k))
        if v is not None:
            subject[k] = v

    comps = pick_comps(
        subject, n=n, months_back=months,
        overrides=forced, excluded=excluded,
    )

    # Layer 1 — AI comp-hygiene (drops bad comps + condition-adjusts) when a
    # key is set and the caller asked for it. Degrades silently otherwise.
    want_ai = bool(payload.get("aiHygiene"))
    hygiene_dropped = []
    if want_ai:
        try:
            from mls_bot.analytics.cma_hygiene import review_comps, apply_hygiene
            from mls_bot.analytics.llm import llm_available
            if llm_available():
                verdicts = review_comps(subject, comps)
                if verdicts:
                    before = {str(c.get("address")) for c in comps}
                    comps = apply_hygiene(comps, verdicts)
                    after = {str(c.get("address")) for c in comps}
                    hygiene_dropped = sorted(before - after)
        except Exception:
            pass

    valuation = _estimate_value(subject, comps)

    # Layer 3 — adversarial review of the final set (optional).
    cma_critique = None
    if want_ai:
        try:
            from mls_bot.analytics.cma_review import review_cma
            cma_critique = review_cma(subject, comps, {
                "mid": _round_to_5k(valuation.mid), "low": _round_to_5k(valuation.low),
                "high": _round_to_5k(valuation.high),
                "divergence_pct": valuation.divergence_pct,
            })
        except Exception:
            cma_critique = None

    elapsed = time.perf_counter() - t0

    # Project comps down to fields the dashboard actually displays.
    def _comp_dict(c):
        return {
            "address":         c.get("address"),
            "city":            c.get("city"),
            "county":          c.get("county"),
            "subdivision":     c.get("subdivision"),
            "parcel_id":       c.get("parcel_id"),
            "listing_id":      c.get("listing_id"),
            "sold_price":      c.get("sold_price"),
            "original_list_price": c.get("original_list_price"),
            "sqft":            c.get("sqft"),
            "acres":           c.get("acres"),
            "year_built":      c.get("year_built"),
            "bedrooms":        c.get("bedrooms"),
            "full_baths":      c.get("full_baths"),
            "half_baths":      c.get("half_baths"),
            "dom":             c.get("dom"),
            "close_date":      str(c.get("close_date") or "") or None,
            "score":           c.get("_score"),
            "distance_mi":     c.get("_distance_mi"),
            "cohort":          c.get("_cohort"),
            "atypical_sale":   bool(c.get("_atypical_sale")),
            "atypical_reason": c.get("_atypical_reason") or None,
            "appearance":      c.get("appearance") or None,
            "appearance_tier": c.get("_appearance_tier"),
            "appearance_adj_pct": c.get("_appearance_adj_pct"),
            "pending":         bool(c.get("_pending")),
            "status":          c.get("_status") or c.get("status_category") or "Closed",
            "forced":          bool(c.get("_forced")),
        }

    out_subject = {
        "address":           subject.get("address"),
        "city":              subject.get("city"),
        "county":            subject.get("county"),
        "subdivision":       subject.get("subdivision"),
        "parcel_id":         subject.get("parcel_id"),
        "status":            subject.get("status_category"),
        "list_price":        subject.get("list_price"),
        "sqft":              subject.get("sqft"),
        "acres":             subject.get("acres"),
        "year_built":        subject.get("year_built"),
        "bedrooms":          subject.get("bedrooms"),
        "full_baths":        subject.get("full_baths"),
        "half_baths":        subject.get("half_baths"),
        "assessed_total":    subject.get("assessed_total"),
        "deed_last_sale_date":  subject.get("deed_last_sale_date"),
        "deed_last_sale_price": subject.get("deed_last_sale_price"),
        "owner":             subject.get("owner"),
        "feed_dom":          subject.get("feed_dom"),
    }
    # Display boundary — the dashboard shows these; keep the $5k convention
    # (ValuationResult itself is unrounded as of the B6 rounding-to-render fix).
    out_valuation = {
        "low":              _round_to_5k(valuation.low),
        "mid":              _round_to_5k(valuation.mid),
        "high":             _round_to_5k(valuation.high),
        "ppsf":             valuation.ppsf,
        "divergence_pct":   valuation.divergence_pct,
        "methods": [
            {
                "name":      m.name,
                "value":     m.value,
                "low":       m.low,
                "high":      m.high,
                "rationale": m.rationale,
            }
            for m in valuation.methods
        ],
    }

    print("__JSON__" + json.dumps(_clean({
        "ok": True,
        "subject":   out_subject,
        "comps":     [_comp_dict(c) for c in comps],
        "valuation": out_valuation,
        "hygiene_dropped": hygiene_dropped,
        "cma_critique": cma_critique,
        "elapsed_seconds": elapsed,
    }), allow_nan=False))
except Exception as e:
    print("__JSON__" + json.dumps({
        "ok": False,
        "error": str(e),
        "traceback": traceback.format_exc(),
    }))
`;

function parsePreviewResult(stdout: string): PreviewResult | null {
  const marker = "__JSON__";
  const idx = stdout.lastIndexOf(marker);
  if (idx === -1) return null;
  try {
    return JSON.parse(stdout.slice(idx + marker.length).trim());
  } catch {
    return null;
  }
}

export async function POST(req: Request) {
  let payload: PreviewRequest;
  try {
    payload = await req.json();
  } catch {
    return NextResponse.json(
      { ok: false, error: "Invalid JSON body" },
      { status: 400 }
    );
  }

  const address = (payload.address ?? "").trim();
  const parcelId = (payload.parcelId ?? "").trim();
  if (!address && !parcelId) {
    return NextResponse.json(
      { ok: false, error: "Provide an address or parcelId." },
      { status: 400 }
    );
  }

  const previewJson = JSON.stringify({
    address,
    parcelId,
    months: payload.months,
    nComps: payload.nComps,
    excluded: payload.excluded,
    forced: payload.forced,
  });

  const { stdout, stderr, code } = await runPython(["-c", RUNNER], {
    PROJECT_ROOT,
    PREVIEW_PAYLOAD: previewJson,
  });
  const parsed = parsePreviewResult(stdout);
  if (!parsed) {
    return NextResponse.json(
      {
        ok: false,
        error:
          code === 0
            ? "Preview returned no JSON marker."
            : `Python exited ${code}.`,
        stderr: stderr.slice(0, 4000),
      },
      { status: 500 }
    );
  }
  if (!parsed.ok) {
    return NextResponse.json(
      { ...parsed, stderr: stderr.slice(0, 4000) },
      { status: 400 }
    );
  }
  return NextResponse.json(parsed);
}

// Convenience GET wrapper so the browser typeahead can fire a preview with
// no JSON body. Maps query string -> POST shape.
export async function GET(req: Request) {
  const url = new URL(req.url);
  const fakeReq = new Request(req.url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      address: url.searchParams.get("address") ?? "",
      parcelId: url.searchParams.get("parcelId") ?? "",
      months: Number(url.searchParams.get("months") ?? "24") || 24,
      nComps: Number(url.searchParams.get("n") ?? "6") || 6,
    }),
  });
  return POST(fakeReq);
}
