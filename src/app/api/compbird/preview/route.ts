import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { enginePreview } from "@/lib/cma/engine";
import { checkRateLimit, getClientIp } from "@/lib/compbird-ratelimit";
import { toEngineOverrides, type SubjectOverrides } from "@/lib/cma/overrides";
import { clampInt, capStringList, COMPBIRD_BOUNDS } from "@/lib/compbird/validate";
import { SESSION_COOKIE, verifyAppSessionToken } from "@/lib/auth";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 30;

interface PreviewResult {
  ok: boolean;
  error?: string;
}

export async function POST(req: Request) {
  // P0 #12: per-IP throttle on the preview spawn (comp set + valuation).
  const rl = checkRateLimit("compbird:preview", await getClientIp());
  if (rl.limited) {
    return NextResponse.json(
      { ok: false, error: "Too many requests. Please slow down." },
      { status: 429, headers: { "Retry-After": String(rl.retryAfterSeconds) } },
    );
  }

  let payload: {
    address?: string;
    parcelId?: string;
    months?: number;
    nComps?: number;
    excluded?: string[];
    forced?: string[];
    subjectOverrides?: SubjectOverrides;
  };
  try {
    payload = await req.json();
  } catch {
    return NextResponse.json({ ok: false, error: "Invalid JSON body" }, { status: 400 });
  }
  // Bound the numeric knobs + comp lists at the parse point (clamp, never 400;
  // non-numeric → undefined = engine defaults) so a crafted payload can't push
  // absurd values or ballooned arrays into the engine.
  payload.months = clampInt(payload.months, COMPBIRD_BOUNDS.months);
  payload.nComps = clampInt(payload.nComps, COMPBIRD_BOUNDS.nComps);
  payload.excluded = capStringList(payload.excluded);
  payload.forced = capStringList(payload.forced);
  // AUTHENTICATED-builder gate. Subject-fact overrides + full LLM hygiene are an
  // authenticated capability; anonymous callers get the read-only AVM-on/LLM-off
  // CMA. The compbird surface is proxy-exempt, but the host session cookie is still
  // readable here, so we enforce at the route. The studio hides the editors for
  // anonymous users — this is the SERVER enforcement behind that.
  const session = await verifyAppSessionToken((await cookies()).get(SESSION_COOKIE)?.value);
  const authed = !!session;

  // toEngineOverrides clamps numerics to OVERRIDE_BOUNDS and maps condition→
  // appearance; for anonymous callers overrides are STRIPPED (undefined) so a
  // crafted payload can never fabricate subject facts into the valuation.
  const { status, body } = await enginePreview<PreviewResult>({
    ...payload,
    subjectOverrides: authed ? toEngineOverrides(payload.subjectOverrides) : undefined,
    aiHygiene: authed, // server-controlled; authed → full hygiene, anon → off
  });
  return NextResponse.json(body, { status });
}
