# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `devin_internals.paths` — canonical store-location resolution
  (D-2026-10-08): `default_data_dir()`/`default_config_dir()` honoring
  `DEVIN_DATA_DIR`/`DEVIN_CONFIG_DIR` and platform (injectable for tests),
  a frozen `DevinPaths` + `resolve()` covering `sessions_db`,
  `session_locks_dir`, `credentials_toml`, `acp_messages_dir`,
  `state_vscdb` and `ecosystem_dir`, plus candidate-order helpers for
  files that may live under data or config roots. `.devin-ecosystem/`
  anchors under the Devin config dir (`~/.config/Devin` on Linux —
  capitalized on every platform), fixing the drifted bare-`XDG_CONFIG_HOME`
  and lowercase-`devin` fallbacks in vendored copies.
- `devin_internals.identity` — shared machine identity:
  `machine_id()` (`DEVIN_MACHINE_ID` or a `secrets.token_hex(8)` persisted
  once at `<ecosystem>/machine-id`, mode `0600`, never regenerated),
  `profile()` (`DEVIN_ECOSYSTEM_PROFILE` → `devin-profile.json` →
  fail-closed `"corporate"`) and `provenance()`.
- 64 new tests (paths + identity): 116 total.

### Changed

- Refreshed the generated `Part of the DEVIN ecosystem` block: journey recuration v2 (six paths, zero repeats, `Local-first ops` label, `devin-bridge` in DevOps).
- Ecosystem journey recuration recorded (six curated audiences); `For: Developers, Maintainers` kept intentionally — maintainers remain an audience even though no curated journey targets them.

- README gains the generated `Part of the DEVIN ecosystem` block
  (track/nature/audience/interface rendered from the registry).

- `labeler.yml` is now a thin caller of the shared reusable workflow in `devin-powerups` (`@v1`); PR labeling behavior is unchanged.

- Install section now recommends pypi `uv tool install devin-internals-spec` as the primary route, with `pipx`/source installs documented as alternatives.

- `llms.txt` no longer states a hard-coded ecosystem size; the registry owns the count.
- Platform guides and the README install command no longer pin a release; they install the latest published version.

## [0.3.1] - 2026-10-13

### Added

- `devin_internals.cursor` — shared incremental-cursor helper: one
  JSON object per cursor at `<dir>/<name>-state.json`, atomic
  `commit()` (tmp + `os.replace`) that merges with on-disk state,
  fail-open reads, `DEVIN_CURSOR_DIR`/explicit `dir=` override.

### Fixed

- `__version__` bumped to match `pyproject.toml` (0.3.1) so the
  publish-version check passes.
- `Cursor` rejects names containing path separators or `..` on every
  platform, undecodable state files read as empty, `commit()` rejects
  non-finite values instead of writing nonstandard JSON.

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
