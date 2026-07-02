import "server-only";
import { promises as fs } from "node:fs";
import path from "node:path";

/**
 * Append-only audit trail for agent CMA control (subject-fact overrides +
 * report-config edits). Whenever the generate route accepts an override or a
 * report-config change, it records ONE JSON line here so an agent-adjusted
 * estimate is always attributable after the fact.
 *
 * Why a JSONL file (mirrors compbird/leads.ts): the audit predates any decision
 * on a logging/analytics store, so events are durably appended as JSON Lines to a
 * writable path. One object per line keeps the file append-only and trivially
 * greppable; a future migration can stream it into whatever store we land on.
 *
 * Path resolution mirrors leads.ts: an explicit env override wins, otherwise we
 * default to `MLS_BOT_ROOT/uploads/compbird-overrides.jsonl` when MLS_BOT_ROOT is
 * set, else `<cwd>/uploads/compbird-overrides.jsonl` (the uploads/ folder already
 * exists and is writable in this single-process deployment).
 *
 * server-only (node:fs). Never imported from a client component or Edge runtime.
 */

const AUDIT_PATH = path.resolve(
  process.env.COMPBIRD_OVERRIDES_PATH ||
    path.join(
      process.env.MLS_BOT_ROOT || process.cwd(),
      "uploads",
      "compbird-overrides.jsonl",
    ),
);

export interface OverrideEvent {
  /**
   * Caller identity — the authenticated user id (AppSessionPayload.userId). The
   * generate route only accepts + logs an override for an authenticated session,
   * so every audited adjustment is attributable to a real signed-in user.
   */
  actorId: string;
  /** Subject address as submitted (may be empty if a parcelId was used). */
  address?: string;
  /** Subject parcel id as submitted (may be empty if an address was used). */
  parcelId?: string;
  /**
   * The engine-shaped (snake-key) override dict actually applied to the
   * valuation — the post-sanitize/post-clamp value from toEngineOverrides, so the
   * audit reflects what the engine saw, not the raw client payload.
   */
  overrides?: Record<string, unknown>;
  /** Which report-config keys were edited (e.g. ["execText"]). Not the text. */
  reportConfigKeys?: string[];
}

/**
 * Append one override event as a JSON line. This is the ONLY mutating entry
 * point.
 *
 * Contract: NEVER throws to the caller. A full disk, a read-only path, or any
 * other fs failure resolves to `false` rather than rejecting — auditing must
 * never break report generation. The route awaits this best-effort before
 * returning, but a `false` is silently tolerated.
 */
export async function logOverrideEvent(event: OverrideEvent): Promise<boolean> {
  try {
    const line = JSON.stringify({
      ts: new Date().toISOString(),
      actorId: event.actorId,
      address: event.address || undefined,
      parcelId: event.parcelId || undefined,
      overrides: event.overrides && Object.keys(event.overrides).length ? event.overrides : undefined,
      reportConfigKeys:
        event.reportConfigKeys && event.reportConfigKeys.length ? event.reportConfigKeys : undefined,
    });
    await fs.mkdir(path.dirname(AUDIT_PATH), { recursive: true });
    await fs.appendFile(AUDIT_PATH, line + "\n", "utf8");
    return true;
  } catch {
    // Swallow: auditing is best-effort and must never break generation.
    return false;
  }
}
