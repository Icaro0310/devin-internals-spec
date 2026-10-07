# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- `llms.txt` no longer states a hard-coded ecosystem size; the registry owns the count.

## [0.3.0] - 2026-10-04

### Added

- `devin_internals.commits` — `commit_references()` extracts git commit
  references (full 40-hex SHAs and `<host>/<owner>/<repo>/commit/<sha>`
  URLs) from `tool_call_state` payloads. Short SHAs are deliberately
  ignored — precision over recall, because these refs feed the knowledge
  graph (IS-5).
- `devin_internals.projects` — `canonical_project_path` /
  `canonical_project_key`: one ecosystem-wide normalization so sessions,
  graph nodes, history notes and memories join on a stable project key
  (IS-4).
- `devin_internals.contract` + `devin-inspect contract` — unified drift
  contract over a Devin data dir: sessions.db schema version,
  acp-messages `meta` shape, a usage-shape probe (verified: no cost/usage
  columns persist in `tool_call_state`) and state.vscdb presence in one
  read-only pass (F4).
- `AcpMessagesStore.typed_meta()` — typed `AcpMeta` view over the
  acp-messages `meta` table (IS-4).
- `devin-inspect vscdb-scan` + `devin_internals.parsers.vscdb_scan` —
  shape-only `state.vscdb` audit: a key-shape census that never reads
  values (IS-1).
- 14 new tests (commits/projects, fixtures, vscdb-scan): 47 total.

## [0.2.0] - 2026-09-29

### Added

- `devin_internals.parsers` — read-only typed parsers per store:
  - `SessionsStore` (`sessions`, `message_nodes`, `tool_call_state`,
    `prompt_history`, `rendered_commits`, `subagent_heads`, `app_state`)
    gated on `detect_schema_version()`; refuses known-but-unsupported
    versions too.
  - `AcpMessagesStore` (`meta` + `messages`) and `StateVscdbStore`
    (`ItemTable`; `get()`/`list_prefix()`/`keys()`) gated on table shape —
    those stores have no migration ledger.
- `devin-inspect` CLI: `schema` (JSON contract), `sessions` (table or
  `--json`, `--limit`), `health` (locates all three stores under a Devin data
  dir; exit code reflects store health). All read-only.
- `fixtures.create_devin_data_dir()` — synthetic `cli/`+`User/` tree for
  `health` consumers/tests.
- `docs/SCHEMA.md` — field-by-field v17 reference, ASCII ER diagram, and the
  explicit v15/v16 DDL gap.
- 19 new tests (parsers + CLI): 33 total.

### Changed

- Console script renamed `devin-internals-spec` → `devin-inspect` (the
  scaffold name had no released behavior).

## [0.1.0] - 2026-09-29

### Added

- `docs/SPEC.md` — canonical English spec covering the three local stores
  (`sessions.db`, `acp-messages/*.db`, `state.vscdb`), translated from
  `docs/SPEC.pt-BR.md`.
- `devin_internals.schema` — `detect_schema_version()` reads
  `refinery_schema_history` + `app_state.schema_compat_version` and raises
  `UnknownSchemaVersionError`/`SchemaDetectionError` loudly on anything it
  doesn't recognise.
- `devin_internals.fixtures` — deterministic (fixed-seed) synthetic generators
  for `sessions.db` (real v17 DDL, synthetic rows), `acp-messages` and
  `state.vscdb`.
- Tests covering fixture validity/determinism, v17 detection, and loud
  failure on unknown/missing/corrupt schemas (Windows + Linux safe).
- Real content in `README.md`/`README.pt-BR.md` (problem, prior art,
  Devin-native extra, limitations).
- Initial scaffold from `devin-repo-template`.
