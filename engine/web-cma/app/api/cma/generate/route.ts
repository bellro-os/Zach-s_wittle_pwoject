import { NextResponse } from "next/server";
import { spawn } from "node:child_process";
import path from "node:path";
import { PROJECT_ROOT, PYTHON_SRC, OUTPUTS_DIR } from "@/lib/paths";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Generation can take 15-45s with auto-fit retries. Give it room.
export const maxDuration = 120;

interface GenerateRequest {
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
}

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
    proc.on("close", (code) => {
      resolve({ stdout, stderr, code: code ?? -1 });
    });
    proc.on("error", (err) => {
      resolve({ stdout, stderr: stderr + String(err), code: -1 });
    });
  });
}

/**
 * Inline runner script that invokes build_cma() and prints a JSON result
 * line. The request payload is passed via the CMA_PAYLOAD environment
 * variable as a JSON string so we never have to interpolate JS literals
 * (``false`` / ``true`` / ``null``) into Python source.
 */
function buildRunner(): string {
  const py = `
import json, os, sys, traceback
from pathlib import Path
ROOT = Path(${JSON.stringify(PROJECT_ROOT)})
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
try:
    from build_cma import build_cma
    payload = json.loads(os.environ.get("CMA_PAYLOAD", "{}"))
    r = build_cma(
        address=payload.get("address") or None,
        parcel_id=payload.get("parcelId") or None,
        brand_name=payload.get("brand") or "gravity",
        agent_name=payload.get("agent") or None,
        comp_overrides=payload.get("comps") or None,
        excluded_comps=payload.get("excluded") or None,
        n_comps=int(payload.get("nComps") or 6),
        months_back=int(payload.get("months") or 24),
        allow_multi_page=bool(payload.get("allowMultiPage")),
        ai_hygiene=bool(payload.get("aiHygiene")),
    )
    print("__JSON__" + json.dumps({
        "ok": True,
        "subject_address": r.subject_address,
        "estimated_value": r.estimated_value,
        "value_low": r.value_low,
        "value_high": r.value_high,
        "comp_count": r.comp_count,
        "pages": r.pages,
        "elapsed_seconds": r.elapsed_seconds,
        "autofit_attempts": r.autofit_attempts,
        "html_path": str(r.html_path),
        "pdf_path": str(r.pdf_path),
    }))
except Exception as e:
    print("__JSON__" + json.dumps({
        "ok": False,
        "error": str(e),
        "traceback": traceback.format_exc(),
    }))
`;
  return py;
}

function parseBuilderResult(stdout: string): BuilderOutput | null {
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
  let payload: GenerateRequest;
  try {
    payload = await req.json();
  } catch {
    return NextResponse.json({ ok: false, error: "Invalid JSON body" }, { status: 400 });
  }

  const address = (payload.address ?? "").trim();
  const parcelId = (payload.parcelId ?? "").trim();
  if (!address && !parcelId) {
    return NextResponse.json(
      { ok: false, error: "Provide an address or parcelId." },
      { status: 400 }
    );
  }

  const runner = buildRunner();
  const cmaPayload = JSON.stringify({
    address,
    parcelId,
    brand: payload.brand,
    agent: payload.agent,
    comps: payload.comps,
    excluded: payload.excluded,
    months: payload.months,
    nComps: payload.nComps,
    allowMultiPage: payload.allowMultiPage,
    aiHygiene: payload.aiHygiene,
  });
  const { stdout, stderr, code } = await runPython(["-c", runner], {
    CMA_PAYLOAD: cmaPayload,
  });
  const parsed = parseBuilderResult(stdout);

  if (!parsed) {
    return NextResponse.json(
      {
        ok: false,
        error:
          code === 0
            ? "Builder returned no JSON marker. Check server logs."
            : `Python exited ${code} before producing a result.`,
        stderr: stderr.slice(0, 4000),
      },
      { status: 500 }
    );
  }
  if (!parsed.ok) {
    return NextResponse.json(
      {
        ok: false,
        error: parsed.error || "Unknown builder error",
        stderr: stderr.slice(0, 4000),
      },
      { status: 500 }
    );
  }

  // Reduce the absolute PDF path back to its basename so the client can fetch
  // it via /api/cma/pdf/[name] without ever seeing the host filesystem layout.
  const pdfName = parsed.pdf_path ? path.basename(parsed.pdf_path) : undefined;
  const htmlName = parsed.html_path ? path.basename(parsed.html_path) : undefined;

  return NextResponse.json({
    ok: true,
    subject: parsed.subject_address,
    valueLow: parsed.value_low,
    valueMid: parsed.estimated_value,
    valueHigh: parsed.value_high,
    compCount: parsed.comp_count,
    pages: parsed.pages,
    elapsedSeconds: parsed.elapsed_seconds,
    autofitAttempts: parsed.autofit_attempts,
    pdfName,
    htmlName,
    outputsDir: OUTPUTS_DIR,
  });
}
