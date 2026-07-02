import "server-only";

/**
 * Client for the warm CMA worker (MLS Bot/worker/cma_worker.py) — a long-lived
 * localhost HTTP service that keeps sklearn + the AVM model + DuckDB resident so
 * profile/CMA requests skip the ~5-12s cold start.
 *
 * Every caller falls back to the per-request `spawnPython` path on ANY failure
 * here (worker down, still warming, busy, timeout, non-200), so the worker is a
 * pure optimization that can never regress the app. `callWorker` throws on
 * failure; the route catches it and spawns instead.
 */

/**
 * Resolve the worker base URL. Precedence (all additive — when none are set the
 * value is byte-identical to the historical hardcoded localhost default):
 *   1. CMA_ENGINE_URL  — point the client at a REMOTE engine (e.g.
 *      "https://engine.internal"); used for /healthz, /profile, /generate.
 *   2. CMA_WORKER_URL  — the original local-override knob (kept for back-compat).
 *   3. http://127.0.0.1:8765 — the long-standing localhost default.
 * Any trailing slash is stripped so callers can safely concatenate "/profile".
 */
export function workerBaseUrl(): string {
  const raw =
    process.env.CMA_ENGINE_URL?.trim() ||
    process.env.CMA_WORKER_URL?.trim() ||
    "http://127.0.0.1:8765";
  return raw.replace(/\/$/, "");
}

const WORKER_URL = workerBaseUrl();

/**
 * Base URL for compbird's OWN engine instance. When COMPBIRD_ENGINE_URL is set,
 * compbird's public /api/compbird/* routes target a SEPARATE engine process — its
 * own tweakable code checkout that shares the read-only data pool — so accuracy
 * experiments on compbird never touch Ratifyly's production engine. When unset,
 * compbird falls back to the shared primary worker (today's single-engine
 * behavior), so absence of the var is a no-op.
 */
export function compbirdWorkerBaseUrl(): string {
  const raw = process.env.COMPBIRD_ENGINE_URL?.trim();
  return raw ? raw.replace(/\/$/, "") : WORKER_URL;
}

export const COMPBIRD_WORKER_URL = compbirdWorkerBaseUrl();

/**
 * Auth headers for the worker/engine call. When CMA_WORKER_TOKEN is set (used to
 * authenticate to a remote engine), send it as a Bearer token; otherwise send no
 * Authorization header, so localhost behavior is unchanged.
 */
export function workerAuthHeaders(): Record<string, string> {
  const token = process.env.CMA_WORKER_TOKEN?.trim();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** Worker is opt-out: set CMA_WORKER_DISABLED=1 to force the spawn path. */
export function workerEnabled(): boolean {
  const off = process.env.CMA_WORKER_DISABLED?.trim().toLowerCase();
  return !(off && off !== "0" && off !== "false" && off !== "no");
}

export async function callWorker<T>(
  path: "/profile" | "/preview" | "/generate",
  body: unknown,
  timeoutMs: number,
  baseUrl: string = WORKER_URL,
): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(baseUrl + path, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        // Bearer token only when CMA_WORKER_TOKEN is set (remote engine auth);
        // no header otherwise, so the localhost call is unchanged.
        ...workerAuthHeaders(),
      },
      body: JSON.stringify(body),
      signal: ctrl.signal,
      // Internal/localhost call — never cache.
      cache: "no-store",
    });
    if (!res.ok) throw new Error(`cma-worker ${res.status}`);
    return (await res.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}
