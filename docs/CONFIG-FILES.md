# CONFIG-FILES.md — config file formats across the Devin install + ecosystem

Ledger of every configuration / bookkeeping file that lives under the two
canonical roots (`<data>` and `<config>` — see `src/devin_internals/paths.py`
for the platform table and env overrides `DEVIN_DATA_DIR` / `DEVIN_CONFIG_DIR`).
The split between **Devin-owned** (written by the CLI/Desktop app) and
**ecosystem-owned** (written by devin-* tools under `.devin-ecosystem/`) is
the load-bearing distinction: ecosystem code may write the second group,
never the first.

Marks: **(verified YYYY-MM-DD)** = inspected live on that date, structure
only — values are never published · **(contract)** = format pinned by the
writer's source, cited per row · **(unverified)** = observed, not inspected.

## 1. Devin-owned files (read-only for tooling)

| file | format | structure | evidence |
|---|---|---|---|
| `<data>/credentials.toml` | TOML, flat string scalars | CLI credentials + endpoints; **full spec: `docs/CREDENTIALS-TOML.md`** | **(verified 2026-10-22)** |
| `<data>/cli/installation_id` | plain text, single line | UUID-shaped install identifier (36 bytes incl. trailing newline) | **(verified 2026-10-22)** |
| `<config>/config.json` | JSON object | top-level keys: `models`, `cascadeRules`, `workflows`, `cascade`, `editor`, `windsurfTab`, `advanced`, `agents`, `devinForTerminal`, `hooks`, `version` (int, observed `1`). `hooks` holds `SessionStart`/`UserPromptSubmit`/`SessionEnd`/`Stop` lists — the hook entrypoints other ecosystem files plug into. Inner key semantics **(unstable)** | **(verified 2026-10-22)** — observed under the legacy lowercase `~/.config/devin` root on Linux (split-layout drift, see `paths.py`) |
| `<config>/mcp_config.json` | JSON object | `{"mcpServers": {"<name>": {command/args/env}}}` — server definitions the Desktop MCP client spawns | **(verified 2026-10-22)**, same legacy root |
| `<config>/api.env` | dotenv `KEY=value` | `DEVIN_API_KEY_V3`, `DEVIN_API_KEY_V1` — **secrets; never read into output** | **(verified 2026-10-22)**, same legacy root |
| `<config>/User/settings.json` | JSON (VS Code settings shape) | editor/workbench preferences | present **(unverified)** |
| `<config>/.devin-migration-complete` | plain text | one-shot migration marker left by a Desktop update | present **(unverified)** |

Chromium/Electron platform files under `<config>` (`Cookies`, `Local State`,
`Preferences`, `Network Persistent State`, `DIPS`, cache dirs, …) belong to
the embedded runtime, not the Devin contract — listed here only so nobody
mistakes them for spec surface. Out of scope.

## 2. Ecosystem-owned files — `<config>/.devin-ecosystem/`

Written by devin-* tools; shared across repos; anchored via
`paths.ecosystem_anchor_dir()` so they never drift with GUI-store layout.

| file | format | structure | evidence |
|---|---|---|---|
| `machine-id` | plain text, one line | 16 lowercase hex chars (`secrets.token_hex(8)`), mode `0600`; written once, never regenerated | **(contract)** `devin_internals.identity`; **(verified 2026-10-22)** shape |
| `devin-profile.json` | JSON object | `{"profile": "corporate" \| "personal"}`; absent means corporate (fail-closed) | **(contract)** `devin_internals.identity` |
| `hooks.json` | JSON object | `{"version": 1, "handlers": {"<Event>": [{"id", "command", "timeout_seconds", "enabled", "profile", "requires"}]}}` — dispatcher registry for `hooks_dispatch.py`; events keyed by `SessionStart`/`UserPromptSubmit`/… | **(contract)** `devin-powerups/tools/hooks_dispatch.py` |
| `scheduled.json` | JSON object | `{"version": 1, "jobs": {"<name>": {"command", "guarded_command", "interval_h", "backend" ("cron"\|"tasksch"\|"elapsed"), "requires_devin_closed", "installed_at", "last_run"}}}` — F6 job registry; `elapsed` jobs are ticked by the `UserPromptSubmit` hook | **(contract)** `devin-state` `devin_install_scheduler.install` / `devin-powerups` `schedule.py` |
| `plans.jsonl` | JSONL, one record per line | `{"ts", "plan_hash", "workers", "mode", "outcome", "notes", "run_id"}` — orchestrator outcome registry; `plan_hash` is a sha256 of the canonical plan JSON | **(contract)** `devin-control` `devin_orchestrator.registry` |
| `metrics/<run_id>.json` | JSON object | per-run metrics doc (`version` 1): `started_ts`/`ended_ts`/`duration_s`, `outcome`, `outcome_counts`, `units[]` | **(contract)** `devin_orchestrator.registry` |
| `skill-catalog.json` | JSON | rendered skill catalog cache written by devin-skill-catalog | present **(unverified — internals not spec'd)** |

## 3. Observed-but-not-config surface (do not spec here)

Directories that hold tool *output* or state, not configuration — recorded
so the boundary stays honest: `<data>/heartbeat/`, `<data>/qa/`,
`<data>/summaries/`, `<data>/cli/summaries/`, `<data>/cli/logs/`,
`<data>/mcp/oauth/`, `<config>/repo-maintenance/`. Content formats belong to
the repo that writes them.

## 4. Reader rules (the contract)

1. **Devin-owned files are read-only.** No ecosystem tool writes
   `credentials.toml`, `config.json`, `mcp_config.json`, `api.env`, or
   `installation_id` — they are Devin's contract surface, and drift is
   handled by re-verification, not by patching.
2. **Values are never published.** Key *names* are structure; anything to
   the right of `=` is row content. Secret-bearing files
   (`credentials.toml`, `api.env`) must never be read into logs, exports or
   model context.
3. **Unknown keys fail open for readers, fail closed for writers.** A reader
   ignores keys it does not know; a writer adds keys only to the file its own
   repo owns (§2), under a `version` field where one exists.
4. **Paths come from `devin_internals.paths`.** Env overrides and the
   Linux split-root / lowercase-sibling candidates are already encoded there;
   do not hand-roll root resolution.

## 5. Known gaps (explicit)

- `config.json` inner sections (`cascade`, `agents`, `hooks` item shape) are
  verified to exist but their field semantics are **unstable** — Cognition
  can rename them any release.
- `devin-profile.json` / `hooks.json` / `scheduled.json` / `plans.jsonl`
  formats are pinned by *our own* writers — drift there is an ecosystem bug,
  not a Devin release event; the version fields are the migration hook.
- `<config>/User/settings.json`, `.devin-migration-complete`,
  `skill-catalog.json` internals: present, not yet inspected.
