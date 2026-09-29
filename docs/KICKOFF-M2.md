# KICKOFF M2 — devin-internals-spec

Continuation of M1 (see `STATUS.md` and `docs/SPEC.md` — read both first).
You are a dedicated session for THIS repository only. Same rules as M1:
fixtures first, `mode=ro` on any real DB, small commits, trailer
`Co-Authored-By: Devin <158243242+devin-ai-integration[bot]@users.noreply.github.com>`,
`git push` at the end, update `STATUS.md` + `CHANGELOG.md` when done.

## Goal

Deliver per-table parsers + the `devin-inspect` CLI. This turns the repo
from "spec + fixtures + detector" into a usable inspection tool.

## Scope (in order)

1. **Parsers** — `src/devin_internals/parsers/` (one module per store):
   - `sessions.py` — sessions, message_nodes, tool_call_state,
     rendered_commits, prompt_history, subagent_heads → typed dataclasses.
     Read-only; return rows as plain dataclasses, never expose raw blobs.
   - `acp_messages.py` — `meta` + `messages` tables.
   - `state_vscdb.py` — `ItemTable` (focus on `windsurfSpace.*` keys;
     expose `get(key)` / `list_prefix(prefix)`).
   - Every parser must call `detect_schema_version()` first and raise on
     unknown versions.
2. **`devin-inspect` CLI** (`src/devin_internals/cli.py` + pyproject script):
   - `devin-inspect schema <path>` — print the detection contract as JSON.
   - `devin-inspect sessions <sessions.db> [--limit N]` — session list
     (id, title, cwd, created_at, status) as table or `--json`.
   - `devin-inspect health <devin-data-dir>` — locate the three stores,
     report which exist, schema versions, row counts.
   - No writes. `--json` on every subcommand for machine consumers.
3. **Tests** — new `tests/test_parsers.py` + `tests/test_cli.py` using the
   M1 fixtures (generate into tmp dirs, same pattern as M1). Cover:
   each parser returns expected records from the v17 fixture; CLI `schema`
   output shape; `health` on a fixture dir; unknown version still fails loud.
4. **`docs/SCHEMA.md`** — field-by-field table doc for v17, with
   "(verified in v17)" marks and an ASCII ER diagram of sessions.db.

## Explicitly OUT of M2 (M3 candidates)

- v15/v16 fixture deltas — we don't have real DDL for them; document the
  gap in SCHEMA.md instead of guessing.
- PyPI publish — needs the name decision + account; not this round.

## Environment notes (from M1)

- `python` = 3.11.9 with pytest; bare `pip` = Python 3.14 → always use
  `python -m pip`.
- Multi-line `python -c` produces no output in this shell — write scripts
  to files instead.
- Windows paths; CRLF warnings on add are harmless.

## Done criteria

- `python -m pytest` — all tests green (M1's 14 + new).
- `python -m devin_internals.cli schema <fixture>` prints the contract.
- `STATUS.md` → M2 done + what remains for M3.
