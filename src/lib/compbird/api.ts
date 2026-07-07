/**
 * Client-side helpers for the public compbird API. Browser-safe (no server
 * imports). Every call hits `/api/compbird/*`, which is exempted from the app
 * auth gate in src/proxy.ts.
 */
import type {
  ProfileResult,
  PropertyMatch,
  SearchResponse,
  GenerateResult,
  PreviewResult,
  NeighborhoodMarket,
  MarketsResponse,
} from "./types";
import type { SubjectOverrides, ReportConfig } from "@/lib/cma/overrides";
import { trackCheckoutStart, trackReportGenerated } from "@/lib/marketing/track";

/**
 * Thrown when a compbird API call returns a non-2xx status. `rateLimited` is
 * true for 429s so callers (e.g. the search bar) can show a "slow down" state
 * instead of treating it as an empty result.
 */
export class CompbirdApiError extends Error {
  readonly status: number;
  readonly rateLimited: boolean;
  /** Machine-readable reason from the server body (e.g. "quota_exceeded"). */
  readonly code?: string;
  constructor(status: number, message?: string, code?: string) {
    super(message ?? `compbird request failed (${status})`);
    this.name = "CompbirdApiError";
    this.status = status;
    this.rateLimited = status === 429;
    this.code = code;
  }
}

/** True for a rate-limit error, so the UI can show a "slow down" message. */
export function isRateLimitError(err: unknown): err is CompbirdApiError {
  return err instanceof CompbirdApiError && err.rateLimited;
}

/** Build a CompbirdApiError from a failed response, lifting the server's
 *  {error, code} JSON so callers can show a precise message (e.g. the 402 → subscribe
 *  CTA) instead of a generic failure. Never throws on a non-JSON body. */
async function toApiError(res: Response): Promise<CompbirdApiError> {
  let message: string | undefined;
  let code: string | undefined;
  try {
    const data = (await res.json()) as { error?: unknown; code?: unknown };
    if (typeof data?.error === "string") message = data.error;
    if (typeof data?.code === "string") code = data.code;
  } catch {
    /* non-JSON / empty body — fall back to the generic message */
  }
  return new CompbirdApiError(res.status, message, code);
}

async function getJSON<T>(url: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(url, { signal, cache: "no-store" });
  if (!res.ok) throw await toApiError(res);
  return (await res.json()) as T;
}

async function postJSON<T>(url: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
    cache: "no-store",
  });
  if (!res.ok) throw await toApiError(res);
  return (await res.json()) as T;
}

export async function searchProperties(
  q: string,
  limit = 8,
  signal?: AbortSignal,
): Promise<PropertyMatch[]> {
  if (q.trim().length < 2) return [];
  const data = await getJSON<SearchResponse>(
    `/api/compbird/search?q=${encodeURIComponent(q)}&limit=${limit}`,
    signal,
  );
  return data.matches ?? [];
}

export async function fetchProfile(
  input: { address?: string; parcelId?: string },
  signal?: AbortSignal,
): Promise<ProfileResult> {
  return postJSON<ProfileResult>("/api/compbird/profile", input, signal);
}

export async function generateReport(input: {
  address?: string;
  parcelId?: string;
  brand?: string;
  agent?: string;
  months?: number;
  nComps?: number;
  allowMultiPage?: boolean;
  /** Comp keys the user excluded in the studio — dropped from the rendered PDF. */
  excluded?: string[];
  /** Addresses the user pinned IN as comps — forced into the rendered PDF. */
  forced?: string[];
  /**
   * Agent CMA control: camelCase subject-fact overrides (sqft + condition are the
   * v1 value-movers; finished-area correction is `sqft` here — the single gated,
   * clamped, audited, and disclosed path). Routes convert via toEngineOverrides.
   */
  subjectOverrides?: SubjectOverrides;
  /**
   * Report composition + the editable exec paragraph (execText). Routes sanitize
   * via sanitizeReportConfig; the legal disclaimer is engine-locked, not here.
   */
  reportConfig?: ReportConfig;
}): Promise<GenerateResult> {
  const result = await postJSON<GenerateResult>("/api/compbird/generate", input);
  // Ad "Lead" event: a report actually generated is the activation moment the
  // ad networks optimize toward. Consent-gated no-op when pixels are absent.
  trackReportGenerated();
  return result;
}

/**
 * Live comp set + valuation for one subject — the studio's working surface.
 * Wraps POST /api/compbird/preview (see src/app/api/compbird/preview/route.ts).
 */
export async function previewComps(
  input: {
    address?: string;
    parcelId?: string;
    months?: number;
    nComps?: number;
    excluded?: string[];
    forced?: string[];
    /**
     * Agent CMA control: camelCase subject-fact overrides (v1 exposes sqft +
     * condition). The route converts to the engine shape via toEngineOverrides.
     */
    subjectOverrides?: SubjectOverrides;
  },
  signal?: AbortSignal,
): Promise<PreviewResult> {
  return postJSON<PreviewResult>("/api/compbird/preview", input, signal);
}

/** Neighborhood market cards for the landing showcase. GET /api/compbird/markets. */
export async function fetchMarkets(signal?: AbortSignal): Promise<NeighborhoodMarket[]> {
  const data = await getJSON<MarketsResponse>("/api/compbird/markets", signal);
  return data.markets ?? [];
}

export function pdfUrl(name: string): string {
  return `/api/compbird/pdf/${encodeURIComponent(name)}`;
}

/**
 * Start a subscription checkout (Stripe). POSTs /api/billing/checkout and, on
 * success, navigates the browser to the hosted Checkout URL. Throws with the
 * server's message otherwise (e.g. "Billing is not configured yet.").
 */
export async function startSubscription(): Promise<void> {
  // Ad conversion funnel marker — consent-gated no-op when pixels are absent.
  trackCheckoutStart();
  const res = await fetch("/api/billing/checkout", { method: "POST", cache: "no-store" });
  const data = (await res.json().catch(() => null)) as
    | { ok?: boolean; url?: string; error?: string }
    | null;
  if (res.ok && data?.ok && data.url) {
    window.location.href = data.url;
    return;
  }
  throw new Error(data?.error || "Could not start checkout.");
}

/** Open the Stripe billing portal to manage/cancel an existing subscription. */
export async function openBillingPortal(): Promise<void> {
  const res = await fetch("/api/billing/portal", { method: "POST", cache: "no-store" });
  const data = (await res.json().catch(() => null)) as
    | { ok?: boolean; url?: string; error?: string }
    | null;
  if (res.ok && data?.ok && data.url) {
    window.location.href = data.url;
    return;
  }
  throw new Error(data?.error || "Could not open billing.");
}
