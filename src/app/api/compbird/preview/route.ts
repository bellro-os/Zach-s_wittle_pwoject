import { NextResponse } from "next/server";
import { enginePreview } from "@/lib/cma/engine";
import { checkRateLimit, getClientIp } from "@/lib/compbird-ratelimit";
import { toEngineOverrides, type SubjectOverrides } from "@/lib/cma/overrides";
import { clampInt, capStringList, COMPBIRD_BOUNDS } from "@/lib/compbird/validate";
import type { PreviewResult } from "@/lib/compbird/types";
import { getActiveContext } from "@/lib/session";
import { can as canFeature } from "@/lib/entitlements";
import { redactEvidence } from "@/lib/compbird/redact";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 30;

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
  // Entitlement resolution (server-side; the compbird surface is proxy-exempt but
  // the host session cookie is readable here, so we enforce at the route):
  //   - `authed` (any signed-in account) → full LLM hygiene on the estimate.
  //   - `evidence` ("cma.evidence", Pro/SOLO+) → subject-fact overrides are
  //     honored AND the response ships un-redacted. FREE + anonymous callers get
  //     overrides STRIPPED (the editors are Pro) and an evidence-REDACTED body —
  //     the estimate stays live, the comps never leave the server.
  const ctx = await getActiveContext();
  const authed = !!ctx;
  const evidence = ctx ? canFeature(ctx.ent, "cma.evidence") : false;

  // toEngineOverrides clamps numerics to OVERRIDE_BOUNDS and maps condition→
  // appearance; for non-evidence callers overrides are STRIPPED (undefined) so a
  // crafted payload can never fabricate subject facts into the valuation.
  const { status, body } = await enginePreview<PreviewResult>({
    ...payload,
    subjectOverrides: evidence ? toEngineOverrides(payload.subjectOverrides) : undefined,
    aiHygiene: authed, // server-controlled; authed → full hygiene, anon → off
  });
  if (body?.ok && !evidence) {
    return NextResponse.json(redactEvidence(body), { status });
  }
  return NextResponse.json(body, { status });
}
