# Heartbeat ledger

Universal "am I alive" signal shared by every devin-* tool, cron job and
daemon. Writers append one JSONL beat per run; readers — silence sensors
such as `ecosystem_sync --freshness` — fold the file into per-tool
`last_success_at` / `last_failure_at` timestamps and flag components that
stopped beating (**dead-but-alive**: scheduled, enabled, silently not
running).

Canonical implementation, vendored verbatim by other repos:

- `src/devin_internals/heartbeat.py` — stdlib-only, single file.
- `src/devin_internals/heartbeat.js` — node >=18 ESM, zero deps.

Vendored copies MUST NOT grow imports — no `devin_internals`, no
third-party packages, no `node_modules`. `python3 heartbeat.py …` and
`node heartbeat.js …` work from any directory.

## Ledger location

First match wins; `ledger_path()` resolves, never creates:

1. `$DEVIN_HEARTBEAT_FILE`
2. `$XDG_STATE_HOME/devin/heartbeats.jsonl`
3. `~/.local/state/devin/heartbeats.jsonl`

The file is append-only JSONL. Emitters `mkdir -p` the parent on first
write. Single-line appends of these short records are atomic enough for
the multi-writer case — no locking is spec'd.

## Line contract

One JSON object per line:

```json
{"ts": 1761924000.123, "tool": "discussion-scout", "event": "success", "detail": null}
```

| field    | type                    | rule |
|----------|-------------------------|------|
| `ts`     | number (epoch seconds)  | writer's clock at emit time |
| `tool`   | string `[a-z0-9-]{1,64}` | sanitized at write: lowercase, runs of invalid chars → `-`, edges stripped, truncated; empty → `"unknown"` |
| `event`  | `"success"` \| `"failure"` | closed vocabulary |
| `detail` | string \| null          | ≤200 chars at write; `run`/`probe` failures use `rc=<n>` + last 120 chars of combined output tail; `spawn-error: <err>` / `empty argv` when the command never ran |

## Emit contract — fail-open by design

`emit_heartbeat()` / `emitHeartbeat()` NEVER raise/throw and return the
ledger path regardless of outcome. A broken or unwritable ledger must not
break the tool it observes — every failure (I/O, path resolution,
serialization) is swallowed. Emitting is cheap and always allowed;
correctness of the *signal* is the reader's problem.

## `run` / `probe` — instrument crontabs, not tool internals

Tools should not need heartbeat code inside them. The wrappers run a
command without a shell, beat `success` iff `rc == 0` (else `failure`
with the `rc=<n>` detail), echo the child's output back to stdout/stderr,
and exit with the command's rc — so a wrapped crontab behaves exactly as
before, plus a beat:

```cron
*/20 * * * *  hb run discussion-scout -- /usr/bin/python3 /opt/scout.py
*/5  * * * *  hb probe office -- curl -sf http://127.0.0.1:8137/healthz
```

(`hb` = the repo-local `heartbeat` wrapper; equivalently
`python3 heartbeat.py run …` / `node heartbeat.js run …`.)

`run` and `probe` are the same contract under two names: `probe` reads as
a liveness check in a crontab — daemon health endpoints, MCP servers,
anything whose *absence of failure* is the signal. Spawn errors return
`127` (shell's command-not-found convention); signal death maps to
`128+signal` (JS) / the subprocess's own negative rc passthrough is
normalized to its `returncode` (Python `subprocess` semantics).

Direct CLIs for ad-hoc beats:

```bash
python3 heartbeat.py emit <tool> [--fail] [--detail txt]   # exit 0 always
python3 heartbeat.py run  <tool> -- <cmd> [args...]        # exit = cmd rc
python3 heartbeat.py probe <tool> -- <cmd> [args...]       # exit = cmd rc
node heartbeat.js emit <tool> [--fail] [--detail txt]
node heartbeat.js run  <tool> -- <cmd> [args...]
```

## Reader contract — `ecosystem_sync --freshness`

`read_heartbeats()` / `readHeartbeats()` folds the ledger into:

```python
{tool: {"last_success_at": ts | None,
        "last_failure_at": ts | None,
        "last_detail":     str | None}}
```

`last_detail` is the detail of that tool's newest beat (max `ts`). The
reader is fail-open: a missing file reads as `{}`; malformed lines —
bad JSON, non-dict, missing/invalid `tool`/`event`/`ts` — are skipped,
never fatal. A corrupt ledger degrades the freshness signal; it must not
crash the sensor.

Freshness is judged against a **per-tool threshold matrix owned by the
consumer** (the ledger intentionally stores no cadence metadata):

| tool class | example | expected cadence → threshold |
|------------|---------|------------------------------|
| hot loop   | `discussion-scout` (every 20 min) | ~1.5× period → 30 min |
| daemon     | `office` (probe every 5 min)      | ~2× period → 10 min |
| daily job  | `answer-runner`, `history-export` | ~26 h |
| weekly job | `weekly-testgen`                  | ~8 d |

Sensor rules, in order:

1. `last_success_at` is `None` → the tool never completed a run —
   report *silent* (no baseline) or *unknown* for optional tools.
2. `now - last_success_at > threshold[tool]` → **silence**:
   dead-but-alive; investigate scheduler/log next.
3. `last_failure_at > last_success_at` → **error streak**: the tool is
   beating but currently failing; `last_detail` carries the wrapper's
   `rc=<n>` + output tail.
4. Otherwise → healthy.

Rule 3 deliberately wins over rule 2 only when the silence threshold is
not also exceeded — a tool failing every cycle still beats, so both can
hold; report the streak.
