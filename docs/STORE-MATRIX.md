# STORE-MATRIX.md — consolidated store × tool coverage matrix

One consolidated view of every on-disk store the spec set names: which
tools **read** it, which **write** it, and its **spec status**. This is a
coverage index, not a contract — where a per-store spec doc exists
(`docs/SCHEMA.md`, `docs/SESSION-SURFACES.md`, `docs/SURFACE-HEALTH.md`,
`docs/SESSION-EVIDENCE.md`, `docs/SCHEMA-VERSIONS.md`,
`docs/CONFIG-FILES.md`, `docs/CREDENTIALS-TOML.md`) that doc stays
normative; this matrix repeats status, never semantics.

Store roots follow `devin_internals.paths`: `<data>` = data root
(`~/.local/share/devin` on Linux), `<config>` = UI config root
(`~/.config/Devin` on Linux), `<ecosystem>` = `<config>/.devin-ecosystem/`,
`<home>` = home dir — platform table and env overrides in
`src/devin_internals/paths.py` and `docs/CONFIG-FILES.md`.

Marks: **spec'd** = layout/format documented in the cited doc ·
**observed-only** = seen on disk, not spec'd (the SCHEMA.md §4
convention) · **(contract)** = format pinned by the ecosystem writer's
own source · **(unstable)** = exists but inner format opaque — treat as
opaque.

Coverage is **what the spec set asserts**: a tool absent from a row is
*unasserted*, not proven a non-reader. Readers never write across the
Devin-owned/ecosystem-owned boundary — `docs/CONFIG-FILES.md` §4.

## 1. Devin-owned stores (written by Devin CLI/Desktop; read-only for tooling)

| store | reads | writes | spec status |
|---|---|---|---|
| `<data>/cli/sessions.db` (incl. `refinery_schema_history` ledger) | `devin_internals` (`SessionsStore`, `detect_schema_version`, `devin-inspect schema`/`sessions`/`health`/`contract`) · `agent-sessions` (TS) + `devin-search` collectors (SESSION-SURFACES §6.1) · devin-assure `qa-pack` provider (SESSION-EVIDENCE §6.1) · devin-doctor (SURFACE-HEALTH §4.1) · `devin-history` (exporter — SPEC §4) | Devin CLI only — all tooling strictly read-only (`mode=ro` + `immutable=1` retry, SURFACES §3) | **spec'd** — SCHEMA.md §1, field-verified v17; v18 registered as observed-drift, gated known/supported (SCHEMA-VERSIONS §1) |
| `<config>/User/acp-messages/<session-uuid>.db` | `devin_internals` (`AcpMessagesStore`, `devin-inspect health`/`contract`) · devin-doctor (SURFACE-HEALTH §4.2) · spec'd for agent-sessions/devin-search, but SESSION-EVIDENCE §6.2: no agent-sessions source or qa-pack provider implements this surface yet — coverage is spec-level only | Devin Desktop only | **spec'd** — SCHEMA.md §2, shape-gated (`meta` + `messages`), no version marker (SCHEMA-VERSIONS §2) |
| `<config>/User/globalStorage/state.vscdb` | `devin_internals` (`StateVscdbStore` `get`/`list_prefix`/`keys`, `vscdb-scan` shape audit, `devin-inspect health`/`contract` presence probe) | Devin Desktop (VS Code workbench state) | **spec'd shape; key space observed-only** — `ItemTable` spec'd SCHEMA.md §3 (`user_version = 1`, SCHEMA-VERSIONS §3); `windsurfSpace.*` key names are row content, never enumerated; out of session-surface scope (SURFACES §8) |
| `<data>/credentials.toml` | `devin_internals.paths` resolves the location (contract); **values never read into output** — secret-bearing, no content reader spec'd (CREDENTIALS-TOML §3) | Devin CLI only — no tool ever writes it | **spec'd** — CREDENTIALS-TOML.md: flat TOML, verified key set (verified 2026-10-22) |
| `<data>/cli/installation_id` | no reader spec'd — format ledgered only | Devin CLI/Desktop | **spec'd** — CONFIG-FILES §1 (verified 2026-10-22): one-line UUID |
| `<config>/config.json` | no spec'd reader; its `hooks` section is the entrypoint the ecosystem's `hooks.json` handlers plug into (CONFIG-FILES §1) | Devin only — read-only for tooling (§4.1) | **spec'd top-level keys** — inner semantics **(unstable)** (CONFIG-FILES §1, §5) |
| `<config>/mcp_config.json` | no spec'd reader | Devin only | **spec'd** — CONFIG-FILES §1 (verified 2026-10-22): `{"mcpServers": …}` |
| `<config>/api.env` | none — secrets; never read into output | Devin only | **spec'd** — CONFIG-FILES §1 (verified 2026-10-22): dotenv `KEY=value` |
| `<config>/User/settings.json` | none spec'd | Devin Desktop | **observed-only** — present, not inspected (CONFIG-FILES §1, §5) |
| `<config>/.devin-migration-complete` | none spec'd | Devin Desktop update (one-shot marker) | **observed-only** — present, not inspected (CONFIG-FILES §1, §5) |
| `<data>/cli/session_locks/` | `devin_internals.paths` resolves the dir only — no content reader spec'd | Devin CLI/Desktop (per-session lock files) | **observed-only** — "observed, not spec'd" (SCHEMA.md §4, SCHEMA-VERSIONS §5) |
| `skill_events_spool.lock` | none spec'd | Devin Desktop | **observed-only** — SCHEMA.md §4 sibling, location not pinned |
| `sessions.db-wal` / `sessions.db-shm` siblings | none — SQLite journal internals | SQLite via the Devin CLI writer | **observed-only** — SCHEMA.md §4 |
| Chromium/Electron platform files (`Cookies`, `Local State`, `Preferences`, `Network Persistent State`, `DIPS`, cache dirs) | none — embedded runtime files, not Devin's contract | embedded Chromium runtime | **explicitly out of scope** — CONFIG-FILES §1 |
| Output/state dirs: `<data>/heartbeat/`, `<data>/qa/`, `<data>/summaries/`, `<data>/cli/summaries/`, `<data>/cli/logs/`, `<data>/mcp/oauth/`, `<config>/repo-maintenance/` | the tool that owns each dir only — no cross-tool reader spec'd | the repo that writes each dir — per-dir ownership not enumerated in the spec set | **observed-only** — CONFIG-FILES §3 ("formats belong to the repo that writes them") |

## 2. Ecosystem-owned stores — `<ecosystem>` (`<config>/.devin-ecosystem/`)

Written by devin-* tooling; shared across repos; anchored via
`paths.ecosystem_anchor_dir()` so they never drift with GUI-store layout
(CONFIG-FILES §2). Devin-owned files are never the write target.

| store | reads | writes | spec status |
|---|---|---|---|
| `machine-id` | every devin-* tool via `devin_internals.identity.machine_id()` | `devin_internals.identity` — once, atomic link-claim, mode `0600`, never regenerated | **spec'd (contract)** — CONFIG-FILES §2 + `devin_internals.identity` |
| `devin-profile.json` | `devin_internals.identity.profile()` — canonical location first, legacy config-root copies next, fail-closed `"corporate"` | devin-* tooling (ecosystem-owned file; contract pinned by `devin_internals.identity`) | **spec'd (contract)** — CONFIG-FILES §2 |
| `hooks.json` | `devin-powerups` `tools/hooks_dispatch.py` (dispatcher registry) | devin-powerups registration tooling | **spec'd (contract)** — CONFIG-FILES §2 |
| `scheduled.json` | the scheduler tick — `elapsed` jobs ticked by the `UserPromptSubmit` hook | `devin-state` `devin_install_scheduler.install` / `devin-powerups` `schedule.py` | **spec'd (contract)** — CONFIG-FILES §2 |
| `plans.jsonl` | `devin-control` `devin_orchestrator.registry` | `devin-control` `devin_orchestrator.registry` | **spec'd (contract)** — CONFIG-FILES §2 |
| `metrics/<run_id>.json` | `devin-control` `devin_orchestrator.registry` | `devin-control` `devin_orchestrator.registry` | **spec'd (contract)** — CONFIG-FILES §2 |
| `skill-catalog.json` | devin-skill-catalog | devin-skill-catalog | **observed-only** — present, internals not spec'd (CONFIG-FILES §2, §5) |
| `<cwd>/.devin/<name>-state.json` (incremental cursors; not under `<ecosystem>`) | `devin_internals.cursor.Cursor` API (`DEVIN_CURSOR_DIR` / explicit `dir` override) | `Cursor.commit()` — the only write, atomic (tmp + `os.replace`), merges on write | **spec'd** — README "Incremental cursors" (spec: devin-powerups `docs/incrementality.md`) |

## 3. Third-party agent session stores (SESSION-SURFACES §6.3–6.5)

Non-Devin surfaces in the closed §1 set. Same doctrine: strictly read-only
for every consumer; the vendor agent is the only writer.

| store | reads | writes | spec status |
|---|---|---|---|
| copilot-cli `session-state/<uuid>/events.jsonl` (+ flat `*.jsonl`, `history-session-state/`) under `$COPILOT_DIR`, `$COPILOT_HOME`, `~/.copilot`; `workspace.yaml` sibling read for `working_dir` | `agent-sessions` + `devin-search` collectors (§6.3) · devin-assure `qa-pack` provider (EVIDENCE §6.3, verified) · devin-doctor (SURFACE-HEALTH §4.3) | GitHub Copilot CLI only | **spec'd** — SESSION-SURFACES §6.3 + SURFACE-HEALTH §4.3 (spec v3.4.4) |
| codex-cli `state_<N>.sqlite` + rollout JSONL (`sessions/`, `archived_sessions/`, `$CODEX_SESSIONS_DIR`) under `$CODEX_HOME`/`~/.codex` | `agent-sessions` + `devin-search` collectors (§6.4) · devin-assure `qa-pack` provider (EVIDENCE §6.4, verified) · devin-doctor (SURFACE-HEALTH §4.4) | OpenAI Codex CLI only | **spec'd** — SESSION-SURFACES §6.4 + SURFACE-HEALTH §4.4 (spec v3.4.4) |
| vscode-chat `chatSessions/<id>.json{,l}` (+ `workspaceStorage/<wsDir>/workspace.json` sibling read for `working_dir`) under `Code`/`Code - Insiders` roots and `~/.vscode-server` | `agent-sessions` + `devin-search` collectors (§6.5) · devin-assure `qa-pack` provider (EVIDENCE §6.5, verified) · devin-doctor (SURFACE-HEALTH §4.5) | VS Code chat only | **spec'd** — SESSION-SURFACES §6.5 + SURFACE-HEALTH §4.5 (spec v3.4.4) |

## 4. Reader/writer index (the same matrix, transposed)

| tool | reads | writes |
|---|---|---|
| `devin_internals` + `devin-inspect` (this repo) | `sessions.db`, `acp-messages/*.db`, `state.vscdb` (typed parsers + `health`/`contract` probes); resolves `credentials.toml`/`session_locks/` paths only | `machine-id` (once), `devin-profile.json` contract, `<cwd>/.devin/*-state.json` cursors — never a Devin-owned store |
| `agent-sessions` (TS) | `sessions.db`, copilot `session-state`, codex `state_<N>.sqlite` + rollouts, vscode-chat `chatSessions` — every refresh, no persistence; devin-chat spec'd, not yet implemented | nothing — metadata listing only |
| `devin-search` collectors (Python) | same surface set as agent-sessions — incremental index | its own index (outside this spec's store list) |
| devin-assure `qa-pack` | `sessions.db`, copilot `session-state`, codex store + rollouts, vscode-chat `chatSessions` (providers verified); devin-chat not yet implemented | nothing in the named stores — audit output is local-only, never persisted evidence |
| devin-doctor (devin-explore) | all five surfaces' stores — health ladder `present`→`readable`→`schema`→`sane`, counts only | nothing — `fix` is advice text, never executed (SURFACE-HEALTH §8) |
| `devin-history` | `sessions.db` (+ GUI stores) for export | export output, never the source stores |
| `devin-powerups` | `hooks.json`, `scheduled.json` (`elapsed` tick) | `hooks.json` registry entries, `scheduled.json` jobs |
| `devin-state` (`devin_install_scheduler`) | `scheduled.json` | `scheduled.json` (`install`) |
| `devin-control` (`devin_orchestrator.registry`) | `plans.jsonl`, `metrics/<run_id>.json` | `plans.jsonl`, `metrics/<run_id>.json` |
| `devin-skill-catalog` | `skill-catalog.json` | `skill-catalog.json` |
| Devin CLI / Devin Desktop | — (the products themselves) | every §1 Devin-owned store |

## 5. Known gaps (explicit)

- **`session_locks/`**, `skill_events_spool.lock`, `sessions.db-wal`/`-shm`
  siblings: observed on disk, not spec'd (SCHEMA.md §4) — no content
  reader exists beyond `paths` resolving the location.
- **`state.vscdb` key space**: `ItemTable` shape is spec'd; the
  `windsurfSpace.*` key names and value semantics are row content and
  were never enumerated (SCHEMA.md §3) — enumerate at runtime with
  `StateVscdbStore.list_prefix()`.
- **`devin-chat` implementation gap**: the surface is spec'd
  (SESSION-SURFACES §6.2) and parsed by `devin_internals`, but neither
  agent-sessions nor a qa-pack provider implements it yet
  (SESSION-EVIDENCE §6.2) — the §1 row marks that coverage spec-level.
- **Per-dir ownership of the CONFIG-FILES §3 output dirs**: the dirs are
  named; which repo writes each is not — formats belong to the writing
  repo.
- **`config.json`/`hooks` inner semantics**: top-level keys verified,
  inner shape **(unstable)** — Cognition can rename any release
  (CONFIG-FILES §5).
- **Unasserted coverage**: tools not named in this spec set (other
  ecosystem repos that read the same stores) are absent from the matrix
  by policy — absence is "not asserted", not "does not read". Extend
  rows only with evidence, never by inference.
- **Remote surfaces** (REST API v3, Devin MCP, DeepWiki MCP) are not
  local stores — `docs/EVIDENCE-EQUIVALENCE.md` owns the equivalence
  study; they are out of scope here.
