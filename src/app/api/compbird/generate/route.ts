import { NextResponse } from "next/server";
import { promises as fs } from "node:fs";
import path from "node:path";
import { randomBytes } from "node:crypto";
import { engineGenerate, OUTPUTS_DIR } from "@/lib/cma/engine";
import { checkRateLimit, getClientIp } from "@/lib/compbird-ratelimit";
import {
  toEngineOverrides,
  sanitizeReportConfig,
  type SubjectOverrides,
  type ReportConfig,
} from "@/lib/cma/overrides";
import {
  clampInt,
  capString,
  capStringList,
  subjectOverridesError,
  COMPBIRD_BOUNDS,
  STRING_CAPS,
} from "@/lib/compbird/validate";
import { bodyTooLarge, BODY_TOO_LARGE_RESPONSE } from "@/lib/compbird/body-limit";
import { logOverrideEvent } from "@/lib/cma/override-audit";
import {
  getActiveContext,
  reserveUsage,
  refundUsage,
  quotaFor,
  type UsageReservation,
} from "@/lib/session";
import { can as canFeature } from "@/lib/entitlements";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 120;

export async function POST(req: Request) {
  // P0 #12: per-IP throttle on the heaviest endpoint (PDF render).
  const rl = checkRateLimit("compbird:generate", await getClientIp());
  if (rl.limited) {
    return NextResponse.json(
      { ok: false, error: "Too many requests. Please slow down." },
      { status: 429, headers: { "Retry-After": String(rl.retryAfterSeconds) } },
    );
  }

  // Size gate BEFORE the body is read — a declared multi-megabyte JSON body is
  // garbage by construction (see body-limit.ts).
  if (bodyTooLarge(req)) {
    return NextResponse.json(BODY_TOO_LARGE_RESPONSE, { status: 413 });
  }

  let payload: {
    address?: string;
    parcelId?: string;
    brand?: string;
    agent?: string;
    months?: number;
    nComps?: number;
    allowMultiPage?: boolean;
    excluded?: string[];
    forced?: string[];
    subjectOverrides?: SubjectOverrides;
    reportConfig?: ReportConfig;
  };
  try {
    payload = await req.json();
  } catch {
    return NextResponse.json({ ok: false, error: "Invalid JSON body" }, { status: 400 });
  }
  // Bound EVERYTHING at the parse point (clamp, never 400; non-numeric/non-
  // string → undefined = engine defaults) so a crafted payload can't push
  // absurd values or ballooned arrays into the engine. `forced` feeds the
  // engine's comp overrides below, so it's capped here too. Rebuilding the
  // object (rather than mutating in place) also DROPS any unknown extra keys,
  // which would otherwise ride the `...payload` spread below straight into the
  // engine's JSON payload unbounded. `reportConfig.sections` is the one
  // unbounded ARRAY inside reportConfig (sanitizeReportConfig allowlists names
  // but not the count — a million valid names would all survive), so it gets
  // the same list cap as the comp lists; narratives are length-capped in
  // sanitizeReportConfig itself.
  if (
    payload.reportConfig &&
    typeof payload.reportConfig === "object" &&
    !Array.isArray(payload.reportConfig) &&
    "sections" in payload.reportConfig
  ) {
    (payload.reportConfig as { sections?: unknown }).sections = capStringList(
      (payload.reportConfig as { sections?: unknown }).sections,
    );
  }
  payload = {
    address: capString(payload.address, STRING_CAPS.address),
    parcelId: capString(payload.parcelId, STRING_CAPS.parcelId),
    brand: capString(payload.brand, STRING_CAPS.brand),
    agent: capString(payload.agent, STRING_CAPS.agent),
    months: clampInt(payload.months, COMPBIRD_BOUNDS.months),
    nComps: clampInt(payload.nComps, COMPBIRD_BOUNDS.nComps),
    // Boolean knob: only a literal `true` turns multi-page on (truthy garbage
    // degrades to the engine default, same idiom as the numeric knobs).
    allowMultiPage: payload.allowMultiPage === true,
    excluded: capStringList(payload.excluded),
    forced: capStringList(payload.forced),
    subjectOverrides: payload.subjectOverrides,
    reportConfig: payload.reportConfig,
  };
  // Subject FACTS are rejected, not clamped: a NaN/Infinity/absurd sqft would
  // otherwise be silently coerced into a rendered report the caller never asked
  // for. Checked BEFORE the quota reserve so a bad payload never burns a credit.
  const factsError = subjectOverridesError(payload.subjectOverrides);
  if (factsError) {
    return NextResponse.json({ ok: false, error: factsError }, { status: 400 });
  }

  // ── Account + Pro gate (the paywall) ──────────────────────────────────────
  // Downloading a full CMA is a Pro-only artifact: the metered "2 free
  // downloads" model is RETIRED. FREE gets the estimate on-screen; comps,
  // analytics, and the rendered report require "cma.evidence" (SOLO, $20/mo)
  // → 403 pro_required. The reserveUsage below stays for SOLO+ (their quota is
  // null = unlimited) purely as usage telemetry, and is REFUNDED if the render
  // fails so the usage rows only count successful reports.
  const ctx = await getActiveContext();
  if (!ctx) {
    return NextResponse.json(
      { ok: false, error: "Create a free account to download reports.", code: "auth_required" },
      { status: 401 },
    );
  }
  if (!canFeature(ctx.ent, "cma.evidence")) {
    return NextResponse.json(
      {
        ok: false,
        error: "Comps, analytics, and report downloads are part of Pro.",
        code: "pro_required",
      },
      { status: 403 },
    );
  }
  const quota = quotaFor(ctx.ent, "cma.generate"); // null = unlimited
  let reservation: UsageReservation;
  try {
    reservation = await reserveUsage("cma.generate", ctx.account.id, quota);
  } catch {
    return NextResponse.json(
      { ok: false, error: "Server is busy. Please retry in a moment." },
      { status: 503 },
    );
  }
  if (!reservation.ok) {
    return NextResponse.json(
      {
        ok: false,
        error: "Full report downloads are part of Pro. Upgrade for every comp and unlimited branded PDFs.",
        code: "quota_exceeded",
      },
      { status: 402 },
    );
  }

  // Authenticated builder: subject-fact overrides + report-config edits + full LLM
  // hygiene always apply now (the studio is account-gated). toEngineOverrides clamps
  // numerics to OVERRIDE_BOUNDS and maps condition→appearance; sanitizeReportConfig
  // allowlists sections + caps narrative length. The legal disclaimer is engine-locked
  // (not in reportConfig), and the record→adjusted disclosure renders server-side
  // whenever an override is applied.
  const engineOverrides = toEngineOverrides(payload.subjectOverrides);
  const reportConfig = sanitizeReportConfig(payload.reportConfig);
  // Custom brand/agent is a whitelabel capability: FREE renders the default
  // (un-whitelabeled) brand; only SOLO+ can stamp a custom brand on the report.
  const canWhitelabel = canFeature(ctx.ent, "cma.whitelabel");

  // AUDIT (append-only, never throws). Attribute the agent-adjusted estimate to the
  // REAL signed-in user.
  if (engineOverrides || reportConfig) {
    await logOverrideEvent({
      actorId: ctx.session.userId,
      address: payload.address,
      parcelId: payload.parcelId,
      overrides: engineOverrides,
      reportConfigKeys: reportConfig ? Object.keys(reportConfig) : undefined,
    });
  }

  // Carry the studio's live tuning into the rendered PDF: pinned-in addresses
  // (`forced`) become the engine's comp overrides, and `excluded` drops comps —
  // so the downloaded report matches the comp set the user tuned on screen.
  let status: number;
  let body: unknown;
  try {
    ({ status, body } = await engineGenerate({
      ...payload,
      comps: payload.forced,
      subjectOverrides: engineOverrides,
      reportConfig,
      aiHygiene: true, // account-gated → full hygiene always
      brand: canWhitelabel ? payload.brand : undefined,
      agent: canWhitelabel ? payload.agent : undefined,
    }));
  } catch (err) {
    await refundUsage(reservation.eventId);
    throw err;
  }

  // If the engine didn't actually produce a report, refund the reserved credit.
  const renderFailed = status >= 400 || (body as { ok?: boolean } | null)?.ok === false;
  if (renderFailed) {
    await refundUsage(reservation.eventId);
    return NextResponse.json(body, { status });
  }

  // Paywall integrity: the engine writes the PDF under a GUESSABLE, address-derived
  // basename (CMA_compbird_<slug>.pdf) into the shared OUTPUTS_DIR, which the public
  // /api/compbird/pdf route serves. Rename it to an unguessable per-render token so
  // the paid artifact can't be fetched or enumerated by address (which would bypass
  // both the account wall and the quota meter), and drop the guessable HTML twin.
  const out = body as { ok?: boolean; pdfName?: string; htmlName?: string };
  if (out?.pdfName) {
    try {
      const token = `CMA_compbird_${randomBytes(24).toString("hex")}.pdf`;
      await fs.rename(path.join(OUTPUTS_DIR, out.pdfName), path.join(OUTPUTS_DIR, token));
      // Best-effort remove the guessable HTML twin (cma_compbird_<slug>.html); the
      // studio never serves it, and the pdf route no longer streams .html at all.
      const htmlTwin =
        out.htmlName ?? out.pdfName.replace(/^CMA_/, "cma_").replace(/\.pdf$/i, ".html");
      await fs.rm(path.join(OUTPUTS_DIR, htmlTwin), { force: true }).catch(() => {});
      out.pdfName = token;
      out.htmlName = undefined;
    } catch {
      // If the rename fails, the report still returns (the pdf route auth-gates and
      // brand-scopes it) — never fail a paid render over a rename hiccup.
    }
  }

  return NextResponse.json(body, { status });
}
