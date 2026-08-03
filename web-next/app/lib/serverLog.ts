// Server-only logging for the route handlers and upstream proxies.
//
// Why this exists: with `output: "standalone"` (next.config.js) the app runs as a
// prebuilt bundle whose ONLY diagnostic channel is the node process's stdout —
// there's no dev overlay and Next logs nothing per-request in production. So when
// a proxied route fails, the browser gets a bare 502 and the server pane stays
// empty, which reads as "the path died for no reason". Everything below exists to
// make that failure visible instead.
//
// Lines are single-line and prefixed so they survive `tmux capture-pane` and stay
// greppable once piped to a file:
//
//   tmux pipe-pane -t stai:web -o 'cat >> ~/logs/web.log'
//   grep -F '[extract-proxy]' ~/logs/web.log
//
// Set WEB_LOG=0 to silence the INFO lines. Errors are always printed — you never
// want the thing you're debugging to be the thing you turned off.

const ENABLED = process.env.WEB_LOG !== "0";

export type LogFields = Record<string, unknown>;

function line(level: string, scope: string, msg: string, fields?: LogFields): string {
  const ts = new Date().toISOString();
  // Only append the JSON blob when there's something in it, so simple lines stay
  // readable rather than ending in a bare "{}".
  const tail = fields && Object.keys(fields).length ? ` ${JSON.stringify(fields)}` : "";
  return `${ts} ${level} [${scope}] ${msg}${tail}`;
}

export function slog(scope: string, msg: string, fields?: LogFields): void {
  if (!ENABLED) return;
  console.log(line("INFO ", scope, msg, fields));
}

export function serr(scope: string, msg: string, fields?: LogFields): void {
  console.error(line("ERROR", scope, msg, fields));
}

// Monotonic per-process request ids. Extraction runs up to OCR_CONCURRENCY (3)
// requests at once and each takes ~100s, so their start/finish lines interleave —
// without an id you can't tell which "finished" belongs to which "start".
let seq = 0;
export function nextReqId(prefix: string): string {
  seq += 1;
  return `${prefix}-${seq}`;
}

// Node attaches a `code` to network failures (ENOTFOUND, ECONNREFUSED, ...) that
// says far more than the message alone. Pull out the fields worth printing.
export function errFields(e: unknown): LogFields {
  const err = e as { message?: string; code?: string; errno?: number; syscall?: string };
  return {
    message: err?.message ?? String(e),
    code: err?.code,
    errno: err?.errno,
    syscall: err?.syscall,
  };
}

// Turn a connection failure into the actual fix, rather than making the reader
// rediscover it. These two account for essentially every upstream failure in this
// app, and both have a specific cause worth naming at the point of failure.
export function connHint(e: unknown, base: string): string | undefined {
  const code = (e as { code?: string })?.code;
  if (code === "ENOTFOUND") {
    return (
      `Cannot resolve the hostname in "${base}". "api" and "mlflow" are docker-compose ` +
      `service names that only resolve inside the compose network — outside it, set ` +
      `API_BASE (e.g. API_BASE=http://127.0.0.1:8000) in the SERVER's environment. ` +
      `Note this is read at runtime, so it must be set on the process, not just at build time.`
    );
  }
  if (code === "ECONNREFUSED") {
    return (
      `Nothing is listening at "${base}". The host resolves but the port is closed — ` +
      `check the upstream service is running and bound to that address.`
    );
  }
  return undefined;
}
