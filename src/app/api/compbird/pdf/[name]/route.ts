import { NextResponse } from "next/server";
import { promises as fs } from "node:fs";
import path from "node:path";
import { OUTPUTS_DIR } from "@/lib/cma/engine";
import { workerBaseUrl, workerAuthHeaders } from "@/lib/cma/worker";
import { STRING_CAPS } from "@/lib/compbird/validate";
import { checkRateLimit, getClientIp } from "@/lib/compbird-ratelimit";
import { getActiveContext } from "@/lib/session";
import { can as canFeature } from "@/lib/entitlements";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Compbird-namespaced output filename prefixes (P0 #15).
 *
 * The engine writes generated files into the SHARED OUTPUTS_DIR as
 * `CMA_<brand>_<slug>.pdf` / `cma_<brand>_<slug>.html` (see MLS Bot
 * scripts/build_cma.py). compbird's engine adapter forces brand="compbird", so
 * every compbird artifact starts with `CMA_compbird_` (PDF, uppercase) or
 * `cma_compbird_` (HTML, lowercase). Constraining the PUBLIC route to ONLY serve
 * these prefixes means a guessed filename can no longer leak a host agent's
 * private CMA (which is rendered under a different brand). The authenticated host
 * route (/api/cma/pdf) is unchanged and still serves the full namespace.
 */
// Compbird artifacts this route may serve. The engine writes CMA_<brand>_*.pdf
// into the SHARED outputs dir; compbird's generate route renames each rendered
// report to an UNGUESSABLE CMA_compbird_<token>.pdf before returning the name, so
// this prefix both scopes to the compbird namespace AND matches the tokenized
// output. HTML twins are no longer served here (the studio only opens the PDF).
const PUBLIC_PDF_PREFIXES = ["CMA_general_", "CMA_compbird_"];

/**
 * Stream a generated CMA PDF by basename only. Hardened four ways: (1) a signed-in,
 * entitled account is required — the paid artifact is never public (mirrors the
 * meter on /api/compbird/generate); (2) the render route hands back an unguessable
 * per-report token, so a report can't be fetched or enumerated by address; (3) path
 * separators / traversal are rejected and only .pdf is allowed; (4) serving is
 * scoped to the compbird brand prefix so a host agent's private CMA never leaks.
 */
export async function GET(_req: Request, ctx: { params: Promise<{ name: string }> }) {
  // P0 #12: per-IP throttle so the file stream can't be hammered.
  const rl = checkRateLimit("compbird:pdf", await getClientIp());
  if (rl.limited) {
    return NextResponse.json(
      { error: "Too many requests. Please slow down." },
      { status: 429, headers: { "Retry-After": String(rl.retryAfterSeconds) } },
    );
  }

  // A downloaded report is a Pro-only artifact — require a signed-in account
  // with "cma.evidence" (mirrors the pro_required gate on /api/compbird/generate).
  // Without this, the file stream would bypass the paywall entirely. The
  // legitimate studio flow opens this URL same-origin, so the session cookie
  // rides along and this passes.
  const active = await getActiveContext();
  if (!active) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  if (!canFeature(active.ent, "cma.evidence")) {
    return NextResponse.json({ error: "forbidden" }, { status: 403 });
  }

  const { name } = await ctx.params;
  // decodeURIComponent throws on malformed percent-encoding ("%zz") — that's a
  // nonsensical request shape, so it 400s instead of bubbling into a 500.
  let safe: string;
  try {
    safe = decodeURIComponent(name ?? "");
  } catch {
    return NextResponse.json({ error: "Invalid file name" }, { status: 400 });
  }

  // Length bound: a basename over the filesystem's 255-byte ceiling cannot
  // exist on disk (tokenized names are 65 chars), so an oversized name is a
  // bad request — and never reaches the fs layer.
  if (!safe || safe.length > STRING_CAPS.fileName || safe.includes("..") || safe.includes("/") || safe.includes("\\")) {
    return NextResponse.json({ error: "Invalid file name" }, { status: 400 });
  }
  const ext = path.extname(safe).toLowerCase();
  if (ext !== ".pdf") {
    return NextResponse.json({ error: "Unsupported file type" }, { status: 400 });
  }

  // Only serve compbird-namespaced artifacts — anything else (a host agent's
  // privately-branded CMA) is 404 even on a correct guess.
  if (!PUBLIC_PDF_PREFIXES.some((p) => safe.startsWith(p))) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  const pdfHeaders = {
    "Content-Type": "application/pdf",
    "Content-Disposition": `inline; filename="${safe}"`,
    "Cache-Control": "private, max-age=0, must-revalidate",
  };

  const full = path.join(OUTPUTS_DIR, safe);
  try {
    const data = await fs.readFile(full);
    return new NextResponse(new Uint8Array(data), { status: 200, headers: pdfHeaders });
  } catch {
    // Local miss. On a shared-volume deploy (dev / the old VPS) that means the
    // file genuinely doesn't exist. On Railway the engine wrote the PDF to ITS
    // OWN volume, which this app service cannot read — so fetch it from the
    // worker's token-gated /outputs endpoint and stream it through. The name is
    // already validated (basename, .pdf, compbird prefix) above, so the proxied
    // request is as safe as the local read.
    try {
      const res = await fetch(`${workerBaseUrl()}/outputs/${encodeURIComponent(safe)}`, {
        headers: workerAuthHeaders(),
        cache: "no-store",
      });
      if (res.ok) {
        const buf = new Uint8Array(await res.arrayBuffer());
        return new NextResponse(buf, { status: 200, headers: pdfHeaders });
      }
    } catch {
      /* engine unreachable — fall through to 404 */
    }
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }
}
