#!/usr/bin/env node
/**
 * Universal heartbeat ledger — ESM mirror of `heartbeat.py`.
 *
 * Any tool, cron job or daemon in the ecosystem appends a one-line JSON
 * record per run so a silence sensor (`ecosystem_sync --freshness` and
 * friends) can detect dead-but-alive components. Spec:
 * `docs/HEARTBEAT.md`.
 *
 * Single-file, zero dependencies, node >=18 — other repos vendor this
 * file verbatim, so it must never grow imports beyond `node:` builtins:
 * `node heartbeat.js emit ...` has to work from any directory.
 *
 * Ledger location, first match wins:
 *   $DEVIN_HEARTBEAT_FILE
 *   $XDG_STATE_HOME/devin/heartbeats.jsonl
 *   ~/.local/state/devin/heartbeats.jsonl
 *
 * Design rules (do not regress — they mirror the Python contract):
 * - `emitHeartbeat` NEVER throws. A broken ledger must not break the
 *   tool it observes — all I/O and path resolution is wrapped.
 * - Tool names are sanitized to `[a-z0-9-]{1,64}` at write time.
 * - Readers are fail-open: malformed lines are skipped, a missing file
 *   reads as an empty map.
 * - `run`/`probe` wrap a command without a shell, beat success iff
 *   `rc === 0`, and return the command's rc — instrument crontabs, not
 *   tool internals.
 */

import { spawnSync } from "node:child_process";
import { appendFileSync, mkdirSync, readFileSync } from "node:fs";
import { constants, homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

export const LEDGER_ENV = "DEVIN_HEARTBEAT_FILE";
export const DETAIL_MAX_CHARS = 200;
export const RUN_TAIL_CHARS = 120;

export function ledgerPath(env = process.env) {
  const override = env[LEDGER_ENV];
  if (override) return resolve(override);
  const stateHome = env.XDG_STATE_HOME || join(homedir(), ".local", "state");
  return join(stateHome, "devin", "heartbeats.jsonl");
}

/** Ledger path resolved at load time — informational; all I/O below
 * re-resolves lazily so env changes take effect. */
export const LEDGER = ledgerPath();

function safeLedgerPath() {
  try {
    return ledgerPath();
  } catch {
    return "heartbeats.jsonl";
  }
}

function sanitizeTool(tool) {
  try {
    const name = String(tool)
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
    const truncated = name.slice(0, 64).replace(/^-+|-+$/g, "");
    return truncated || "unknown";
  } catch {
    return "unknown";
  }
}

/**
 * Append one beat to the ledger; returns the path written to.
 * Line contract: {"ts": <epoch float>, "tool": "<sanitized>",
 * "event": "success"|"failure", "detail": "<short>"|null}
 * NEVER throws — every failure is swallowed.
 */
export function emitHeartbeat(tool, { success = true, detail = null } = {}) {
  const path = safeLedgerPath();
  try {
    const record = {
      ts: Date.now() / 1000,
      tool: sanitizeTool(tool),
      event: success ? "success" : "failure",
      detail: detail == null ? null : String(detail).slice(0, DETAIL_MAX_CHARS),
    };
    mkdirSync(dirname(path), { recursive: true });
    appendFileSync(path, JSON.stringify(record) + "\n", "utf8");
  } catch {
    // the ledger must never break the tool it observes
  }
  return path;
}

/**
 * Fold the ledger into per-tool last-seen timestamps:
 * {tool: {last_success_at: ts|null, last_failure_at: ts|null,
 *         last_detail: str|null}}
 * `last_detail` comes from the newest beat for that tool (max ts).
 * Fail-open: missing file -> {}, malformed lines are skipped.
 */
export function readHeartbeats(path = null) {
  const ledger = path || safeLedgerPath();
  const out = {};
  let lines;
  try {
    lines = readFileSync(ledger, "utf8").split("\n");
  } catch {
    return out;
  }
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) continue;
    let rec;
    try {
      rec = JSON.parse(line);
    } catch {
      continue;
    }
    if (!rec || typeof rec !== "object" || Array.isArray(rec)) continue;
    const { tool, event, ts, detail } = rec;
    if (typeof tool !== "string" || !tool) continue;
    if (event !== "success" && event !== "failure") continue;
    if (typeof ts !== "number" || !Number.isFinite(ts)) continue;
    const slot =
      out[tool] ||
      (out[tool] = {
        last_success_at: null,
        last_failure_at: null,
        last_detail: null,
        _latest_ts: -Infinity,
      });
    const key = event === "success" ? "last_success_at" : "last_failure_at";
    if (slot[key] === null || ts > slot[key]) slot[key] = ts;
    if (ts >= slot._latest_ts) {
      slot._latest_ts = ts;
      slot.last_detail = typeof detail === "string" ? detail : null;
    }
  }
  for (const slot of Object.values(out)) delete slot._latest_ts;
  return out;
}

function echo(stdout, stderr) {
  try {
    if (stdout && stdout.length) process.stdout.write(stdout);
    if (stderr && stderr.length) process.stderr.write(stderr);
  } catch {
    // output passthrough is best-effort
  }
}

/**
 * `hb run <tool> -- <cmd...>` / `hb probe <tool> -- <cmd...>`: run
 * cmdArgs without a shell, beat success iff rc === 0 (failure detail:
 * `rc=<n>` + last RUN_TAIL_CHARS of combined output), return the
 * command's rc — 127 when the command cannot be spawned, 128+signal on
 * signal death, matching shell conventions so wrappers stay invisible
 * to callers. `run` and `probe` are the same contract; `probe` is the
 * name for daemon health checks.
 */
export function run(tool, cmdArgs) {
  const argv = [...(cmdArgs || [])];
  if (argv.length && argv[0] === "--") argv.shift();
  if (!argv.length) {
    emitHeartbeat(tool, { success: false, detail: "empty argv" });
    return 127;
  }
  const proc = spawnSync(argv[0], argv.slice(1), {
    shell: false,
    encoding: "buffer",
  });
  if (proc.error) {
    emitHeartbeat(tool, {
      success: false,
      detail: `spawn-error: ${proc.error.message || proc.error}`,
    });
    return 127;
  }
  echo(proc.stdout, proc.stderr);
  const signalNo =
    proc.status == null && proc.signal
      ? constants.signals[proc.signal] || 0
      : 0;
  const rc = proc.status == null ? 128 + signalNo : proc.status;
  if (rc === 0) {
    emitHeartbeat(tool, { success: true });
  } else {
    const tail = Buffer.concat(
      [proc.stdout, proc.stderr].filter(Boolean)
    )
      .toString("utf8")
      .slice(-RUN_TAIL_CHARS);
    emitHeartbeat(tool, {
      success: false,
      detail: `rc=${rc} ${tail}`.trim(),
    });
  }
  return rc;
}
export const probe = run;

function usage() {
  process.stderr.write(
    "usage:\n" +
      "  heartbeat.js emit  <tool> [--fail] [--detail txt]\n" +
      "  heartbeat.js run   <tool> -- <cmd> [args...]\n" +
      "  heartbeat.js probe <tool> -- <cmd> [args...]\n"
  );
}

export function main(argv = process.argv.slice(2)) {
  const [cmd, ...rest] = argv;
  if (cmd === "emit") {
    // exit 0 always — even on bad args
    let tool = null;
    let fail = false;
    let detail = null;
    for (let i = 0; i < rest.length; i++) {
      const a = rest[i];
      if (a === "--fail") fail = true;
      else if (a === "--detail") detail = rest[++i] ?? null;
      else if (!a.startsWith("--") && tool === null) tool = a;
    }
    if (tool !== null) {
      emitHeartbeat(tool, { success: !fail, detail });
    }
    return 0;
  }
  if (cmd === "run" || cmd === "probe") {
    const [tool, ...tail] = rest;
    if (!tool) {
      usage();
      return 2;
    }
    return run(tool, tail);
  }
  usage();
  return 0;
}

// CLI block: only when executed directly (`node heartbeat.js ...`),
// not when imported as a module.
const invokedAs = process.argv[1]
  ? pathToFileURL(resolve(process.argv[1])).href
  : "";
if (import.meta.url === invokedAs) {
  try {
    process.exitCode = main();
  } catch {
    // emit never reaches here (returns 0 internally); a crash in a
    // run/probe wrapper must surface as failure, not success.
    process.exitCode = 1;
  }
}
