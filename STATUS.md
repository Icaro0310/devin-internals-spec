# STATUS — devin-internals-spec

Updated: 2026-09-29 · Milestone: **M2 (done)** · Version: 0.2.0

## Done in M1

- `docs/SPEC.md` (EN translation), real READMEs (EN/PT-BR), deterministic
  fixtures (v17 `sessions.db` real DDL + synthetic rows, `acp-messages`,
  `state.vscdb`), schema-version detector, 14 tests, 0.1.0 changelog.

## Done in M2

- `src/devin_internals/parsers/` — one read-only module per store, all
  returning frozen dataclasses:
  - `sessions.py` — `SessionsStore` → `Session`, `MessageNode`,
    `ToolCallState`, `PromptHistoryEntry`, `RenderedCommit`, `SubagentHead`,
    plus `app_state()`/`counts()`. Gates on `detect_schema_version()`;
    refuses unknown (>17) *and* known-but-unsupported (<15) versions.
  - `acp_messages.py` — `AcpMessagesStore` → `meta()` dict + `messages()`.
  - `state_vscdb.py` — `StateVscdbStore` → `get()`, `list_prefix()`,
    `keys()`; UTF-8 decodes BLOB values.
- `devin-inspect` CLI (`cli.py`, thin wrapper): `schema` (JSON contract),
  `sessions` (table/`--json`, `--limit`), `health` (locates the three stores
  under a data dir, reports existence/versions/counts, exit 0=OK 1=degraded).
- `fixtures.create_devin_data_dir()` — synthetic `cli/`+`User/` tree.
- `docs/SCHEMA.md` — field-by-field v17 doc, ASCII ER diagram, "(verified in
  v17)"/"unstable" marks, explicit v15/v16 gap section.
- 19 new tests → **33 total, all green** (Windows, Python 3.11.9, pytest 9.1.1).
- Renamed console script `devin-internals-spec` → `devin-inspect`; version
  0.2.0. Verified: `python -m devin_internals.cli schema <fixture>` prints
  the contract; `devin-inspect.exe` resolves on PATH.

## Environment notes (unchanged from M1)

- `python` = 3.11.9 w/ pytest; bare `pip` → Python 3.14. Always `python -m pip`.
- exec runs under **cmd.exe**, not bash: no heredocs, no multi-line
  `python -c`; commit messages need repeated `-m` flags.

## Decisions / notes

- acp/vscdb stores have no `refinery_schema_history` → parsers gate on
  table shape (`meta`+`messages`, `ItemTable`) instead of a version. Documented
  in SCHEMA.md.
- acp `meta` key names remain `fixture.*` placeholders (real keys = row
  content, not inspected); `meta()` treats the key space as open.
- Fixture DBs are generated at test time (not committed binaries) —
  `create_devin_data_dir` covers the `health` layout.

## Remaining for M3 (per spec §10)

1. v15/v16 fixtures + compat tests — blocked on real migration evidence
   (ledger rows are content; need an old DB or a published migration list).
2. `devin-inspect` on real stores — M2 verified against fixtures only.
3. PyPI publish (`pipx install devin-internals-spec`) — name decision +
   account needed.
4. CI on Linux (workflow already delegates to `devin-ci` reusable workflow;
   confirm it runs pytest matrix).
5. Optional: `--watch`/nightly schema drift check; `session_locks/` spec;
   read-only MCP (only if requested).

## Blockers

None.
