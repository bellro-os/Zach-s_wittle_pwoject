import { spawn, spawnSync } from "node:child_process";
import path from "node:path";
import { createLogger } from "@/lib/utils/logger";

const log = createLogger("spawnPython");

/**
 * Cross-repo bridge to the MLS Bot Python engine.
 *
 * The Python engine + all its data (Parquet lookups, brand YAML, generated
 * PDFs) live in a SEPARATE repository on disk. This host app reaches them via
 * the MLS_BOT_ROOT env var — nothing is copied into the host. Every Python
 * invocation runs with cwd = PROJECT_ROOT and PYTHONPATH rooted at that
 * engine's src/ (the inline runners additionally push scripts/ onto sys.path).
 */

/**
 * Absolute path to the MLS Bot repo root, or "" when unset. The production
 * deploy reaches the engine over CMA_ENGINE_URL (the warm worker) and NEVER
 * spawns Python locally, so MLS_BOT_ROOT is intentionally absent there.
 * Importing this module must therefore NEVER throw — the local-spawn fallback
 * (`spawnPython`) fails cleanly when this is empty instead.
 */
export const PROJECT_ROOT: string = process.env.MLS_BOT_ROOT?.trim() || "";

/** The MLS Bot src/ tree — added to PYTHONPATH for every spawn (local mode only). */
export const PYTHON_SRC = PROJECT_ROOT ? path.join(PROJECT_ROOT, "src") : "";
/** config/brands/*.yaml — brand profiles consumed by listBrands() (local mode only). */
export const BRANDS_DIR = PROJECT_ROOT ? path.join(PROJECT_ROOT, "config", "brands") : "";
/**
 * outputs/ — where the engine writes generated PDFs/HTML, streamed by
 * /api/cma/pdf. CMA_OUTPUTS_DIR lets the deploy point the app at a mounted
 * engine-outputs volume independent of MLS_BOT_ROOT (the engine writes there;
 * the app reads it read-only).
 */
export const OUTPUTS_DIR =
  process.env.CMA_OUTPUTS_DIR?.trim() || (PROJECT_ROOT ? path.join(PROJECT_ROOT, "outputs") : "");

/** Python interpreter on PATH. Override with PYTHON_BIN. */
export const PYTHON_BIN = process.env.PYTHON_BIN?.trim() || "python";

export interface SpawnResult {
  stdout: string;
  stderr: string;
  code: number;
  /** True when the child was killed by the timeout watchdog (not a clean exit). */
  timedOut?: boolean;
}

export interface SpawnOptions {
  /**
   * Hard wall-clock limit. On expiry the child AND its descendants are killed
   * (no zombies), and the call resolves with `timedOut: true` and a negative
   * code. Defaults to SPAWN_DEFAULT_TIMEOUT_MS; pass per-route values that match
   * each route's maxDuration so we kill before the platform does.
   */
  timeoutMs?: number;
}

/**
 * Hard timeout + concurrency limits for Python spawns. The Python engine reads
 * Parquet and (optionally) drives headless Chrome — a wedged interpreter would
 * otherwise hold a request socket open until the platform timeout and pile up
 * memory. Tunable via env so ops can dial them without a redeploy.
 */
export const SPAWN_DEFAULT_TIMEOUT_MS = clampInt(
  process.env.PYTHON_SPAWN_TIMEOUT_MS,
  120_000,
  1_000,
  600_000
);
/** Max simultaneous Python children. Excess spawns queue FIFO. */
export const SPAWN_MAX_CONCURRENCY = clampInt(
  process.env.PYTHON_MAX_CONCURRENCY,
  4,
  1,
  64
);
/**
 * Cap on how long a spawn may sit in the admission queue before we give up and
 * surface a clean "busy" error rather than holding the request indefinitely.
 */
export const SPAWN_QUEUE_TIMEOUT_MS = clampInt(
  process.env.PYTHON_QUEUE_TIMEOUT_MS,
  30_000,
  1_000,
  600_000
);

function clampInt(
  v: string | undefined,
  def: number,
  min: number,
  max: number
): number {
  const n = v == null ? NaN : parseInt(v, 10);
  if (!Number.isFinite(n)) return def;
  return Math.min(max, Math.max(min, n));
}

// ─── admission control (max-concurrency cap) ───────────────────────────────

let activeSpawns = 0;
const waiters: Array<() => void> = [];

/**
 * Acquire a concurrency slot. Resolves immediately when under the cap, else
 * queues FIFO. Rejects if it waits longer than SPAWN_QUEUE_TIMEOUT_MS so a
 * spawn storm degrades to a clean error instead of unbounded queueing.
 */
function acquireSlot(): Promise<void> {
  if (activeSpawns < SPAWN_MAX_CONCURRENCY) {
    activeSpawns++;
    return Promise.resolve();
  }
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      const idx = waiters.indexOf(grant);
      if (idx !== -1) waiters.splice(idx, 1);
      reject(
        new Error(
          `Python spawn queue timeout: ${SPAWN_MAX_CONCURRENCY} engine processes already running`
        )
      );
    }, SPAWN_QUEUE_TIMEOUT_MS);
    const grant = () => {
      if (settled) {
        // Already timed out — hand our slot to the next waiter instead.
        releaseSlot();
        return;
      }
      settled = true;
      clearTimeout(timer);
      activeSpawns++;
      resolve();
    };
    waiters.push(grant);
  });
}

/** Release a slot and wake the next queued waiter, if any. */
function releaseSlot(): void {
  activeSpawns = Math.max(0, activeSpawns - 1);
  const next = waiters.shift();
  if (next) next();
}

/** Snapshot of the spawn pool — surfaced by /api/health. */
export function spawnPoolStats(): {
  active: number;
  queued: number;
  maxConcurrency: number;
} {
  return {
    active: activeSpawns,
    queued: waiters.length,
    maxConcurrency: SPAWN_MAX_CONCURRENCY,
  };
}

/**
 * Kill a child process and its whole descendant tree. On Windows a plain
 * `proc.kill()` only signals the direct child — the Python interpreter often
 * spawns helpers (headless Chrome for PDF render), which would be orphaned and
 * leak. `taskkill /T /F` tears down the entire tree by pid. On POSIX we signal
 * the process group (spawned with no detached flag, so fall back to the pid).
 */
function killTree(pid: number | undefined): void {
  if (!pid) return;
  try {
    if (process.platform === "win32") {
      spawnSync("taskkill", ["/PID", String(pid), "/T", "/F"], {
        stdio: "ignore",
      });
    } else {
      // Negative pid targets the group; fall back to the bare pid if the child
      // wasn't its own group leader.
      try {
        process.kill(-pid, "SIGKILL");
      } catch {
        process.kill(pid, "SIGKILL");
      }
    }
  } catch {
    /* the watchdog also calls proc.kill() as a backstop */
  }
}

/**
 * Spawn the MLS Bot Python engine and collect its stdout/stderr.
 *
 * `args` are passed verbatim after `-X utf8` — pass either an inline runner
 * (`["-c", RUNNER]`) or a script invocation (`["scripts/foo.py", "<arg>"]`).
 * `payloadEnv` is merged into the child env on top of the inherited process
 * env + the PYTHONPATH / encoding / PROJECT_ROOT bridge variables.
 *
 * Hardening:
 *  - max-concurrency cap (SPAWN_MAX_CONCURRENCY) — excess spawns queue FIFO and
 *    surface a clean error if they wait past SPAWN_QUEUE_TIMEOUT_MS.
 *  - hard timeout (opts.timeoutMs) — on expiry the child AND its descendant
 *    tree are killed (killTree) so a wedged interpreter / headless Chrome never
 *    becomes a zombie; the call resolves with `timedOut: true`, code -1.
 *  - stderr + exit code are always captured.
 *
 * Never rejects — spawn errors, non-zero exits, queue saturation, and timeouts
 * all resolve with the collected output + a `code` so callers handle every
 * failure as data.
 */
export async function spawnPython(
  args: string[],
  payloadEnv: Record<string, string> = {},
  opts: SpawnOptions = {}
): Promise<SpawnResult> {
  const timeoutMs = opts.timeoutMs ?? SPAWN_DEFAULT_TIMEOUT_MS;

  // Remote-engine deploys leave MLS_BOT_ROOT unset and use CMA_ENGINE_URL; the
  // local spawn path is unavailable there. Fail cleanly as data (callers fall
  // back to the warm worker) instead of spawning with an empty cwd.
  if (!PROJECT_ROOT) {
    return {
      stdout: "",
      stderr: "MLS_BOT_ROOT is not set — local Python engine unavailable; use the remote engine via CMA_ENGINE_URL.",
      code: -1,
    };
  }

  try {
    await acquireSlot();
  } catch (err) {
    // Queue saturated — never threw before, so resolve as data with a clear
    // signal callers can map to a 503.
    log.error("Spawn rejected by admission control", err, spawnPoolStats());
    return {
      stdout: "",
      stderr: err instanceof Error ? err.message : String(err),
      code: -2,
    };
  }

  try {
    return await new Promise<SpawnResult>((resolve) => {
      const env: NodeJS.ProcessEnv = {
        ...process.env,
        PYTHONPATH: process.env.PYTHONPATH
          ? `${PYTHON_SRC}${path.delimiter}${process.env.PYTHONPATH}`
          : PYTHON_SRC,
        PYTHONIOENCODING: "utf-8",
        PROJECT_ROOT,
        ...payloadEnv,
      };
      const proc = spawn(PYTHON_BIN, ["-X", "utf8", ...args], {
        cwd: PROJECT_ROOT,
        env,
        shell: false,
      });
      let stdout = "";
      let stderr = "";
      let timedOut = false;
      let settled = false;

      const finish = (result: SpawnResult) => {
        if (settled) return;
        settled = true;
        clearTimeout(watchdog);
        resolve(result);
      };

      const watchdog = setTimeout(() => {
        timedOut = true;
        log.error("Python spawn timed out — killing process tree", undefined, {
          timeoutMs,
          pid: proc.pid,
        });
        killTree(proc.pid);
        // Backstop in case taskkill/group-kill missed it.
        try {
          proc.kill("SIGKILL");
        } catch {
          /* already gone */
        }
        // Resolve now rather than waiting for the (possibly slow) close event so
        // the caller isn't held past the timeout.
        finish({
          stdout,
          stderr:
            stderr +
            `\n[spawnPython] killed after ${timeoutMs}ms timeout`,
          code: -1,
          timedOut: true,
        });
      }, timeoutMs);

      proc.stdout.on("data", (b) => {
        stdout += b.toString();
      });
      proc.stderr.on("data", (b) => {
        stderr += b.toString();
      });
      proc.on("close", (code) => {
        if (timedOut) return; // already resolved by the watchdog
        finish({ stdout, stderr, code: code ?? -1 });
      });
      proc.on("error", (err) => {
        if (timedOut) return;
        finish({ stdout, stderr: stderr + String(err), code: -1 });
      });
    });
  } finally {
    releaseSlot();
  }
}

/**
 * Parse a Python runner's stdout by taking the slice AFTER the last `__JSON__`
 * marker and JSON.parse-ing it. Returns null when no marker is present or the
 * slice isn't valid JSON. (Same convention web-cma uses across every route —
 * the marker survives stray prints/warnings the engine may emit before it.)
 */
export function parseBuilderResult<T = unknown>(stdout: string): T | null {
  const marker = "__JSON__";
  const idx = stdout.lastIndexOf(marker);
  if (idx === -1) return null;
  try {
    return JSON.parse(stdout.slice(idx + marker.length).trim()) as T;
  } catch {
    return null;
  }
}
