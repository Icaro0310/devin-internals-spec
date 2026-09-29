# STATUS — devin-internals-spec

Updated: 2026-09-29 · Milestone: **M1 (done)**

## Done in M1

- `docs/SPEC.md` — canonical English translation of `docs/SPEC.pt-BR.md`.
- `README.md` / `README.pt-BR.md` — real content (problem with the 17-migration
  timeline, prior art: tokmesh/UniSessions, Devin-native extra, install
  placeholder, limitations).
- `src/devin_internals/fixtures.py` — deterministic generators (seed
  `0xD317`, byte-identical output verified by test):
  - `create_sessions_db()` — real v17 DDL (inspected read-only from the live
    store via `sqlite_master`/`PRAGMA table_info` only), fully synthetic rows
    for all 8 tables; `schema_version` knob for compat/unknown-version tests.
  - `create_acp_messages_db()` — `meta` + `messages` (real DDL, synthetic rows).
  - `create_state_vscdb()` — `ItemTable` + `user_version=1`, synthetic
    `windsurfSpace.*` keys.
- `src/devin_internals/schema.py` — `detect_schema_version()`:
  `{"schema_version", "schema_compat_version", "known", "supported",
  "verified", "min_supported": 15, "max_supported": 17}`; raises
  `UnknownSchemaVersionError` (v>17) and `SchemaDetectionError`
  (missing file/table/empty ledger). Opens `mode=ro`, never writes.
- `tests/` — 14 tests, all green on Windows (Python 3.11.9, pytest 9.1.1):
  fixtures open & populated, byte-determinism, v17 detection, loud failure on
  v99, unsupported-but-known older versions, non-sessions DBs, no DB mutation.
- `CHANGELOG.md` — 0.1.0 entry.

## Environment notes

- `python` = 3.11.9 (has pytest); bare `pip` resolves to Python 3.14 —
  use `python -m pip` for installs. Fixed during the session.
- Multi-line `python -c` under this MINGW shell produces no output; use script
  files instead (observed, worked around).

## Remaining for M2 (per spec §10)

1. `sessions.db` parser per table (sessions, message_nodes, tool_call_state,
   rendered_commits, prompt_history, subagent_heads) → typed records.
2. v15/v16 fixtures + compat tests (DDL deltas unknown — v16/v17 were additive;
   needs the real migration list, which is row content we did not read in M1).
3. `acp-messages`/`state.vscdb` parsers (`meta`/`messages`, `ItemTable`).
4. `docs/SCHEMA.md` — field-by-field doc + ER diagram ("verified in v17" marks).
5. CLI `devin-inspect`: `schema`, `sessions`, `health` (thin wrapper, pyproject
   script currently points at `devin-internals-spec`; decide final name).
6. PyPI publish (`pipx install devin-internals-spec`) + CI check on Linux.

## Decisions / deviations from spec

- Fixtures are **generated at test time** into tmp dirs, not committed as
  binary `.db` files (`.gitignore` already excludes `*.db`; generated fixtures
  stay deterministic cross-platform). Revisit if spec §6 "versioned in repo"
  is meant literally.
- Meta keys in the acp fixture are `fixture.*` placeholders — the real `meta`
  key names are row content and were not inspected; M2 parser should treat
  meta keys as an open set.
- Detector treats versions 1–14 as *known but unsupported* (`supported:
  False`), 15–17 supported, 17 verified; >17 raises.

## Blockers

None.
