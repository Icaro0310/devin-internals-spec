# Kickoff M1 — devin-internals-spec

You are a dedicated Devin session for the repository **devin-internals-spec**
(your working directory IS the repo root). You work autonomously; the human
orchestrator reviews your git history and STATUS.md afterwards.

## Context

- This repo belongs to the `devin-*` powerups ecosystem (hub: `Icaro0310/devin-powerups`).
- Public docs use one shared English `README.md` plus `README.windows.md` and
  `README.linux.md` for OS-specific setup. License: MIT; all guides carry the
  unofficial notice.
- Architecture rule: logic lives in `src/devin_internals/` (the library);
  the CLI is a thin wrapper.
- TDD: **fixtures before parsers**. Deterministic fixtures (fixed seed).
- Tests must pass on Windows and Linux.

## Authoritative spec

`docs/SPEC.pt-BR.md` (Portuguese). Your first deliverable includes the
canonical English translation at `docs/SPEC.md`.

## Read-only evidence you may use

The REAL local stores exist at (inspect **read-only**, via Python `sqlite3`
— schema only: `sqlite_master`, `PRAGMA table_info`). NEVER copy row content
into fixtures — fixtures use **synthetic data only**. NEVER write to these DBs.

- `%APPDATA%\devin\cli\sessions.db` — tables:
  `sessions`, `message_nodes`, `tool_call_state`, `prompt_history`,
  `rendered_commits`, `subagent_heads`, `app_state`, `refinery_schema_history`
- `%APPDATA%\devin\User\acp-messages\*.db` —
  per-GUI-session DBs with `meta` + `messages`
- `%APPDATA%\devin\User\globalStorage\state.vscdb` —
  key/value store (`windsurfSpace.*` keys)

Python 3.11: ``py -3.11` (or `python` on PATH)`
(`python` should be on PATH — verify). This is Windows; mind console encoding.

## Milestone M1 scope (do exactly this, no more)

1. `docs/SPEC.md` — canonical EN translation of the spec.
2. Keep shared purpose and usage in `README.md`; put Windows- and Linux-specific
   install/path instructions in their respective guides. Include prior art,
   Devin-native behavior, and limitations.
3. `src/devin_internals/fixtures.py` — deterministic generator:
   `sessions.db` v17 (real DDL inspected read-only, synthetic rows),
   `acp-messages` fixture (`meta`+`messages`), `state.vscdb` fixture.
4. `src/devin_internals/schema.py` — version detector reading
   `refinery_schema_history`/`app_state`; raises a clear error on unknown
   versions.
5. `tests/` — fixtures generate valid DBs that open; detector detects v17;
   unknown version fails loudly.
6. Run `pytest` — all green.
7. Update `CHANGELOG.md` (0.1.0).
8. Write `STATUS.md` at repo root: what was done, what remains for M2,
   any blockers.
9. Commit in small logical commits with the trailer:
   `Generated with [Devin](https://devin.ai)` +
   `Co-Authored-By: Devin <158243242+devin-ai-integration[bot]@users.noreply.github.com>`
   Then `git push` (origin is configured).

## Hard rules

- Stay inside the repo directory.
- No network calls except `git push` and pip installs if needed.
- No telemetry, no secrets, no real session content in fixtures or docs.
- If something blocks you, document it in STATUS.md and stop cleanly.
