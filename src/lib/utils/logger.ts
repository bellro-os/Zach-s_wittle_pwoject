type LogContext = Record<string, unknown>;

export type LogLevel = "info" | "warn" | "error";

/**
 * A single structured log record handed to the active sink. `time` is an ISO
 * timestamp, `scope` is the createLogger() scope, `msg` the human message, and
 * `fields` the merged structured context (an `err` field carries the stringified
 * error message for the error() path). Keeping this shape stable lets a future
 * aggregator transport (JSON-lines file, HTTP shipper, OTel) consume the same
 * records the console sink renders.
 */
export interface LogRecord {
  time: string;
  level: LogLevel;
  scope: string;
  msg: string;
  fields?: LogContext;
}

/** A log transport. Must never throw — see safeEmit(). */
export type LogSink = (record: LogRecord) => void;

function fmt(ctx?: LogContext): string {
  if (!ctx || Object.keys(ctx).length === 0) return "";
  try {
    return ` ${JSON.stringify(ctx)}`;
  } catch {
    // Circular / non-serializable context must not break a log line.
    return " [unserializable-context]";
  }
}

/**
 * Default sink — preserves the previous console rendering verbatim so existing
 * log scraping / dev ergonomics are unchanged. error() folds its `err` field
 * back into the ` :: message` suffix it used to print.
 */
const consoleSink: LogSink = (r) => {
  const fields = r.fields ? { ...r.fields } : undefined;
  if (r.level === "error") {
    const err = fields && "err" in fields ? String(fields.err ?? "") : "";
    if (fields) delete fields.err;
    const suffix = err ? ` :: ${err}` : "";
    console.error(`[${r.scope}] ${r.msg}${suffix}${fmt(fields)}`);
    return;
  }
  const line = `[${r.scope}] ${r.msg}${fmt(fields)}`;
  if (r.level === "warn") console.warn(line);
  else console.log(line);
};

let activeSink: LogSink = consoleSink;

/**
 * Swap the global log transport. Pass nothing (or `null`) to restore the
 * default console sink. Lets logs later route to an aggregator without touching
 * any createLogger() call site. The replacement is process-wide.
 */
export function setLogSink(sink: LogSink | null | undefined): void {
  activeSink = sink ?? consoleSink;
}

/** Restore the built-in console sink. */
export function resetLogSink(): void {
  activeSink = consoleSink;
}

/**
 * Emit through the active sink, but never let a misbehaving transport take down
 * a caller: a throwing sink falls back to console.error and is otherwise
 * swallowed (logging must not become a new failure mode).
 */
function safeEmit(record: LogRecord): void {
  try {
    activeSink(record);
  } catch (sinkErr) {
    try {
      console.error(`[logger] sink threw — falling back to console`, sinkErr);
      consoleSink(record);
    } catch {
      /* give up: never throw from a log call */
    }
  }
}

export interface Logger {
  info(msg: string, ctx?: LogContext): void;
  warn(msg: string, ctx?: LogContext): void;
  error(msg: string, err?: unknown, ctx?: LogContext): void;
}

export function createLogger(scope: string): Logger {
  return {
    info(msg: string, ctx?: LogContext) {
      safeEmit({ time: new Date().toISOString(), level: "info", scope, msg, fields: ctx });
    },
    warn(msg: string, ctx?: LogContext) {
      safeEmit({ time: new Date().toISOString(), level: "warn", scope, msg, fields: ctx });
    },
    error(msg: string, err?: unknown, ctx?: LogContext) {
      const errMsg = err instanceof Error ? err.message : err ? String(err) : "";
      // Fold the error into the structured fields so aggregator sinks see it as
      // data; the console sink renders it back into the legacy ` :: msg` suffix.
      const fields: LogContext | undefined =
        errMsg || ctx ? { ...(ctx ?? {}), ...(errMsg ? { err: errMsg } : {}) } : undefined;
      safeEmit({ time: new Date().toISOString(), level: "error", scope, msg, fields });
    },
  };
}
