import "server-only";

import { spawn } from "node:child_process";
import path from "node:path";

import { createLogger } from "@/lib/utils/logger";
import { workerEnabled, workerBaseUrl, workerAuthHeaders } from "@/lib/cma/worker";

const log = createLogger("cma-worker-supervisor");

const g = globalThis as unknown as { __cmaWorkerStarted?: boolean };

// Shared base-URL resolver (CMA_ENGINE_URL → CMA_WORKER_URL → localhost). When
// none are set this is byte-identical to the prior hardcoded localhost default.
const WORKER_URL = workerBaseUrl();
const PORT = process.env.CMA_WORKER_PORT?.trim() || "8765";

/** Worker liveness snapshot. `warm` mirrors the worker's `/healthz` body (the
 * sklearn + AVM model are loaded) when reachable; undefined when the worker is
 * down or the field is absent. */
export interface CmaWorkerStatus {
  alive: boolean;
  warm?: boolean;
}

/**
 * Ping the warm CMA worker's `/healthz`. Short timeout, never throws — a down
 * worker resolves to `{ alive: false }`. Surfaced by /api/health as a pure
 * optimization signal (the worker being down never fails the probe). When the
 * worker is configured-off (CMA_WORKER_DISABLED) we skip the network call.
 */
export async function cmaWorkerStatus(timeoutMs = 1500): Promise<CmaWorkerStatus> {
  if (!workerEnabled()) return { alive: false };
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), timeoutMs);
    const res = await fetch(`${WORKER_URL}/healthz`, {
      signal: ctrl.signal,
      cache: "no-store",
      // Bearer token only when CMA_WORKER_TOKEN is set (remote engine auth).
      headers: workerAuthHeaders(),
    });
    clearTimeout(t);
    if (!res.ok) return { alive: false };
    let warm: boolean | undefined;
    try {
      const body = (await res.json()) as { warm?: unknown };
      if (typeof body?.warm === "boolean") warm = body.warm;
    } catch {
      // /healthz body unparseable — still alive, just no warm signal.
    }
    return { alive: true, warm };
  } catch {
    return { alive: false };
  }
}

async function isAlive(): Promise<boolean> {
  return (await cmaWorkerStatus()).alive;
}

/**
 * Start (and keep alive) the warm CMA worker as a child of this Next process so
 * a single `next start` boots everything. Idempotent per process. If a worker
 * is already serving the port (an orphan from a prior run, or one started
 * manually), it's reused instead of double-spawned. Best-effort: if MLS_BOT_ROOT
 * is unset or the worker keeps crashing, the CMA routes simply fall back to a
 * per-request `python` spawn — no boot failure.
 */
export function startCmaWorker(): void {
  if (g.__cmaWorkerStarted) return;
  if (!workerEnabled()) {
    log.info("CMA worker disabled (CMA_WORKER_DISABLED) — routes will spawn per request");
    return;
  }
  const root = process.env.MLS_BOT_ROOT?.trim();
  if (!root) {
    log.warn("MLS_BOT_ROOT unset — not starting CMA worker; CMA routes will spawn per request");
    return;
  }
  g.__cmaWorkerStarted = true;
  const py = process.env.PYTHON_BIN?.trim() || "python";

  let restarts = 0;
  const launch = async () => {
    if (await isAlive()) {
      log.info("CMA worker already serving — reusing it", { url: WORKER_URL });
      return;
    }
    log.info("starting CMA worker child", { port: PORT });
    const proc = spawn(py, ["-X", "utf8", "worker/cma_worker.py"], {
      cwd: root,
      env: {
        ...process.env,
        CMA_WORKER_PORT: PORT,
        PYTHONIOENCODING: "utf-8",
        PYTHONPATH: process.env.PYTHONPATH
          ? `${path.join(root, "src")}${path.delimiter}${process.env.PYTHONPATH}`
          : path.join(root, "src"),
      },
      shell: false,
    });
    proc.stdout.on("data", (b) => log.info(`[worker] ${b.toString().trim()}`));
    proc.stderr.on("data", (b) => log.warn(`[worker] ${b.toString().trim()}`));
    proc.on("exit", (code) => {
      log.warn("CMA worker exited", { code, restarts });
      if (restarts >= 20) {
        log.error("CMA worker crash-looping — giving up; CMA routes will spawn per request");
        return;
      }
      restarts++;
      setTimeout(() => void launch(), Math.min(30_000, 1000 * restarts));
    });
  };

  void launch();
}
