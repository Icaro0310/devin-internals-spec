# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- `docs/SCHEMA.md` §4: the v15/v16 gap bullet now scopes "fixtures model
  v17" to v17's *layout* — the vendored v18/v19 stores pin the
  ledger-marker boundary, so "v17 only" no longer reads as if no v18
  fixture exists.
- `pr-approve` caller repinned from v1.6 to v1.9 in `auto-approve.yml`
  (the v1.9 gate fixes the self-cancel so a successful approval no
  longer renders as a failed check, and adds fresh-head recheck plus
  paginated dedup); `tests/test_auto_approve_gate.py` pins the caller
  contract.
- `actions/download-artifact` bumped to v8.0.2 in `pypi-publish.yml`;
  `tests/test_pypi_publish_handoff.py` now pins the `dist` handoff
  contract (`needs: verify`, artifact name/path, v4+-compatible hash pin,
  merged-origin guard, OIDC upload shape).
- `pr-approve` caller bumped from v1.1 to v1.6 in `auto-approve.yml`
  (the v1.6 gate adds cross-repo fix anchors and gate-eligible
  concurrency) and gains the `pull_request_review_comment` trigger so
  fix-commit replies re-evaluate the gate on the same head;
  `tests/test_auto_approve_gate.py` pins the caller contract.
- `actions/setup-python` bumped from `v7.0.0` to `v7.1.0` in
  `tests.yml` (Dependabot).

### Added

- `docs/STORE-MATRIX.md` — consolidated store × tool × read/write
  coverage matrix: every store the spec set names (Devin-owned,
  ecosystem-owned `.devin-ecosystem/`, third-party agent surfaces), who
  reads it, who writes it, and its spec status (spec'd vs observed-only
  per the SCHEMA.md §4 convention). Consolidation only — the per-store
  spec docs stay normative. Post-review corrections: per-OS paths link
  out to the platform READMEs instead of duplicating Linux defaults;
  `devin-profile.json` writer attribution corrected to the operator
  (declared profile — no tool writes it); v18 status aligned with
  `schema.py` (known-but-unverified observed drift).

### Fixed

- `docs/SCHEMA-VERSIONS.md` supported range updated to `15..18` with a
  v18 ledger row — the doc still claimed `15..17` after #56 registered
  v18 as known in `schema.py` (`LATEST_KNOWN_SCHEMA = 18`,
  `VERIFIED_SCHEMA = 17`); the row documents the devin-dream D06 drift
  fixture provenance and the known-vs-verified distinction.
- Three spec ledgers under `docs/`:
  - `docs/SCHEMA-VERSIONS.md` — schema-version drift matrix across Devin
    releases (per-store version marker, latest verified version, first-seen
    release, evidence) plus the drift protocol for when a new version lands
    (issue #1). Documents the live-verified `refinery_schema_history`
    semantics: `applied_on` is an install-time replay timestamp, not a
    release date, and `app_state.schema_compat_version` does not reliably
    mirror `MAX(version)`.
  - `docs/CONFIG-FILES.md` — config/bookkeeping file formats across the
    data/config roots: Devin-owned files (`config.json`, `mcp_config.json`,
    `api.env`, `credentials.toml`, `installation_id`) and ecosystem-owned
    `.devin-ecosystem/` files (`machine-id`, `devin-profile.json`,
    `hooks.json`, `scheduled.json`, `plans.jsonl`, `metrics/`), each marked
    verified/contract/unverified.
  - `docs/CREDENTIALS-TOML.md` — the `credentials.toml` spec: candidate
    locations, flat-TOML format, verified key set, and reader rules
    (read-only, secrets never published).
  All three verified against a live install on 2026-10-22 (Linux).
- `devin_internals/corpus/` package data + `devin_internals.corpus_access` —
  both committed corpora (`fixtures/session-corpus/`,
  `fixtures/install-states/`) now ship inside the wheel under
  `devin_internals/corpus/`, so downstream consumers (devin-assure
  qa-pack, devin-explore doctor) can drop their vendored copies and the
  drift risk that came with them. `corpus_root(name)` returns the
  `importlib.resources` `Traversable`; `materialize_corpus(dest, name)`
  copies a corpus to a real directory for consumers that need real files
  (sqlite stores, fixture trees passed as paths). A `corpus` extra
  documents the contract (stdlib-only, no dependencies). The committed
  `fixtures/` copies remain the source of truth; a drift test
  byte-compares the packaged tree against them.
- 8 new tests (corpus access + packaged↔committed drift guard): 162
  total.

- Schema **v18 registered** (`LATEST_KNOWN_SCHEMA` 17 → 18, in both
  `schema.py` and `fixtures.py`): the detector gates v18 `known` +
  `supported`. Provenance is *observed-drift* — the version row exists
  in the devin-dream D06 drift artifact — so a new `VERIFIED_SCHEMA = 17`
  keeps the contract's `verified` field honest (v18's real migration
  name/DDL were never inspected). `> 18` still raises
  `UnknownSchemaVersionError`.
- `fixtures/schema-versions/` corpus + packaged mirror — detector
  boundary artifacts: `sessions-v18.db` (the real devin-dream D06
  "Schema-drift canary" store, vendored byte-verbatim from devin-assure's
  evals corpus, sha256-pinned in `manifest.json`) and `sessions-v19.db`
  (synthetic, first unregistered version). `schema-versions` joins
  `CORPORA` in `corpus_access`.
- `fixtures/install-states/` regenerated: devin-cli `healthy`/`alt-root`
  stores now carry 18-row ledgers (byte-identical artifacts are
  unchanged). docs/SCHEMA.md §4 + SURFACE-HEALTH known-set updated.

- `docs/SURFACE-HEALTH.md` — canonical spec for per-surface *installation
  health*, the substrate the generalized agent environment doctor
  (devin-doctor) reports on: the ordered check ladder
  (`present` → `readable` → `schema` → `sane`), the `Finding` model
  (`check`/`status`/`code`/`note`/`message`/`fix`), the closed finding
  vocabulary (`store-missing`, `store-corrupt`, `unreadable`,
  `schema-old`, `schema-unknown`, `empty-store`, `store-empty` plus the
  `not-installed` PASS-level note), per-surface version markers and
  known sets, and the CLI contract (`--surface` scoping, absent surfaces
  grouped under "not detected", never failed). Surface checks may
  structurally parse a store to validate it (a `.json` snapshot cannot
  be validated without parsing) but never extract or report content —
  same privacy doctrine as SESSION-SURFACES §8, sharpened.
- `devin_internals.install_states` + committed `fixtures/install-states/` —
  a deterministic corpus of synthetic *installation-state* trees, sibling
  to `fixtures/session-corpus/`: 32 minimal fixtures — home-directory
  surrogates holding each surface's real §6-relative layout — covering
  `healthy`, `absent`, `alt-root` (store under a non-primary candidate:
  devin-cli's legacy config root, codex's external `$CODEX_SESSIONS_DIR`
  rollouts, vscode-chat's remote `~/.vscode-server` root),
  `missing-store`, `empty-store`, `zero-rows` (valid devin-chat db with
  0 messages), `corrupt-store`, `schema-old` (devin-cli ledger v14) and
  `schema-unknown` (ledger v99, missing expected
  tables/envelope/recognizable keys) states across all five surfaces,
  plus `install-states-manifest.json` declaring per-fixture
  `expected_findings` — what a conformant doctor must report.
  `locked-or-unreadable` is deliberately unmodeled (not deterministically
  reproducible cross-platform). Regenerate with `python -m
  devin_internals.install_states fixtures/install-states`.
- 7 new tests (install-states corpus, incl. a reference checker that
  re-derives expected findings from the generated bytes): 154 total.

- `docs/SESSION-EVIDENCE.md` — canonical spec for the session *content*
  layer `SESSION-SURFACES.md` §8 excludes: the `SessionEvidence` model
  (`EvidenceMessage`/`EvidenceToolCall`), the normalized role and
  tool-call-kind vocabularies (`_EXECUTE_KINDS`), the ground-truth
  precedence rule (structured tool evidence outranks message text),
  per-surface extraction mappings for all five surfaces, the local-only
  privacy contract, and the `evidence-manifest.json` parity contract —
  the substrate a generalized qa-pack claims-vs-evidence audit builds on.
- `fixtures/session-corpus/evidence-manifest.json` + evidence coverage in
  the corpus: copilot `alpha` gains the observed
  `tool.execution_start`/`tool.execution_complete` pair and a 'tests
  passed' claim; codex gains `rollout-exec-claim.jsonl` (claim + pytest
  exec record exiting 0 → `verified`) and `rollout-bare-claim.jsonl`
  (claim with no tool evidence → `no-evidence`); vscode-chat `snap-a`
  gains `message` text and `response` parts (markdown claim + terminal
  `toolInvocation`).
- `devin_internals.fixtures` helpers for codex `response_item` records
  (message / `function_call` / `function_call_output` paired by
  `call_id`).
- 2 new tests (evidence manifest): 147 total.

- `devin_internals.session_corpus` + committed `fixtures/session-corpus/` —
  the deterministic fixture corpus required by `docs/SESSION-SURFACES.md` §7:
  synthetic stores for `copilot-cli` (all three §6.3 layouts — primary
  `session-state/<uuid>/`, flat `<uuid>.jsonl`, legacy
  `history-session-state/`), `codex-cli` (`state_4.sqlite` `threads` plus
  `sessions/` rollout JSONL covering open-task, forked and duplicate
  records, §6.4) and `vscode-chat` (final snapshot, mutation-log replay with
  a truncated tail, `emptyWindowChatSessions` global session, §6.5), and a
  `manifest.json` declaring the expected canonical fields (id presence,
  state, spec warning codes, event counts, ISO timestamps — never content).
  Regenerate with `python -m devin_internals.session_corpus
  fixtures/session-corpus`.
- `fixtures.create_copilot_session_state` / `create_codex_store` /
  `create_vscode_chat_storage` — deterministic seeded builders for the three
  non-Devin stores, same pattern as the existing Devin-store generators.
- 9 new tests (session corpus): 143 total.

- `docs/SESSION-SURFACES.md` — canonical spec for multi-agent session
  sources (D-2026-10-15): closed surface vocabulary (`vscode-chat`,
  `copilot-cli`, `codex-cli`, `devin-cli`, `devin-chat`), the canonical
  `SessionMeta` contract, the normative `ended_at` inference chain with
  mandatory warning codes, per-surface store layouts, and the fixture
  corpus + parity-test model shared by the TypeScript and Python
  implementations.
- `docs/SCHEMA.md` — cross-note that `sessions.created_at` /
  `last_activity_at` are epoch **seconds** on Linux v17 stores (vs ms on
  the Windows-verified layout); readers discriminate by `< 1e12`.
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

- `docs/SESSION-EVIDENCE.md` §6 — store-layout facts verified by the
  qa-pack evidence providers (devin-assure #74) are now recorded as
  **(verified)** with attribution: a "verification status" note under
  each surface header names the verifying implementation (qa-pack
  provider, 191-event real-store census, agent-sessions TS parser,
  `devin_internals` parsers). §6.3 gains the copilot event-envelope
  keys, `data.toolCallId` pairing, `data.success` completions, message
  text keys and the `workspace.yaml` seed; §6.4 gains the codex rollout
  type vocabulary (`local_shell_call`, `exec_command_begin`,
  shell-named `function_call`, `local_shell_call_output`,
  `function_call_output`), `session_meta` keys, the JSON-string `output`
  field nesting `metadata.exit_code`, argv-list commands and the
  last-line `Exit code: N` status convention (bare-integer outputs are
  stdout, never status); §6.5 gains the vscode-chat mutation-kind
  semantics, `workspace.json` `folder` URI resolution (Windows
  drive-letter slash artifact, hashed-id never-fabricated rule) and
  `toolSpecificData.terminalCommandState.exitCode`; §6.1's
  `tool_call_state` no-per-call-timestamp gap is re-confirmed.
- Refreshed the generated `Part of the DEVIN ecosystem` block: journey recuration v2 (six paths, zero repeats, `Local-first ops` label, `devin-bridge` in DevOps).
- Ecosystem journey recuration recorded (six curated audiences); `For: Developers, Maintainers` kept intentionally — maintainers remain an audience even though no curated journey targets them.

- README gains the generated `Part of the DEVIN ecosystem` block
  (track/nature/audience/interface rendered from the registry).

- `labeler.yml` is now a thin caller of the shared reusable workflow in `devin-powerups` (`@v1`); PR labeling behavior is unchanged.

- Install section now recommends pypi `uv tool install devin-internals-spec` as the primary route, with `pipx`/source installs documented as alternatives.

- `llms.txt` no longer states a hard-coded ecosystem size; the registry owns the count.
- Platform guides and the README install command no longer pin a release; they install the latest published version.

## [0.3.2] - 2026-10-14

### Added

- Streaming `iter_*` counterparts for every list-returning table method:
  `SessionsStore.iter_sessions` / `iter_message_nodes` /
  `iter_tool_call_state` / `iter_prompt_history` / `iter_rendered_commits` /
  `iter_subagent_heads` and `AcpMessagesStore.iter_messages`. Each accepts a
  `batch_size` (default 2000) and yields the same frozen dataclasses via
  `cursor.fetchmany`, so consumers with large stores (e.g. devin-search's
  indexer) no longer materialize whole tables. The list methods are
  unchanged and now simply drain the matching iterator.
- `SessionsStore.max_ids()` — `MAX(pk)` per append-only table
  (`message_nodes`, `prompt_history`, `rendered_commits`; 0 when empty) so
  watermark-based consumers can detect pruned sources without a full scan.

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
