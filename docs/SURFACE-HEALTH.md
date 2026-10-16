# SURFACE-HEALTH.md — canonical spec for per-surface installation health

The contract for reporting the *health of each agent surface's on-disk
store* — the substrate the **agent environment doctor** (devin-doctor,
generalized from Devin-only diagnostics) reports on. SESSION-SURFACES.md
specifies reading session *metadata* out of live stores;
SESSION-EVIDENCE.md specifies the content layer. This spec sits **one
layer below both**: is the store there, does it open read-only, is its
schema one we know, does it look used? It never parses sessions — the
substrate is installation **state**, not session content.

**Rule: implement from this document, never from another implementation's
code.** When implementations disagree, the bug is in whichever side
diverges from this text — and the text, once corrected, is updated in the
same PR as the fix (same posture as SESSION-SURFACES, D-2026-10-15).

Marks: **(verified)** = observed in a real store · **(unstable)** = format
opaque/unverified — treat as opaque.

---

## 1. Scope and relationship to SESSION-SURFACES

- `surface` uses the **closed set** in SESSION-SURFACES §1 — never outside
  it: `vscode-chat`, `copilot-cli`, `codex-cli`, `devin-cli`, `devin-chat`.
- Expected store roots are the SESSION-SURFACES §6 roots/candidates
  verbatim; this spec adds no locations of its own.
- The SESSION-SURFACES §3 read contract applies minus its metadata
  columns: stores open strictly read-only (SQLite `mode=ro`, retry
  `immutable=1`, a constructed-but-failed handle `close()`d before
  retry); files are read, never written; one broken surface never blocks
  the others — it degrades to its own findings only.
- **Checks never read message CONTENT** — same privacy doctrine as
  SESSION-SURFACES §8. Magic bytes, the first-line envelope shape, table
  names, version ledgers/pragmas, and row *counts* are in scope; message
  bodies, titles, and payload text are never inspected.
- **Global checks stay tool-agnostic by design.** Disk space,
  filesystem permissions, PATH resolution, config syntax — the doctor
  owns those as its own sections. They are not per-surface findings and
  are out of scope here.

## 2. Canonical model — the ordered check ladder

Per-surface health is an **ordered check ladder**. Each rung emits at
most one `Finding`:

| field | type | contract |
|---|---|---|
| `check` | enum | `present` \| `readable` \| `schema` \| `sane` — the rung that produced it |
| `status` | enum | `PASS` \| `WARN` \| `FAIL` |
| `code` | enum \| absent | a §5 finding code — emitted on WARN/FAIL findings; PASS findings carry none |
| `note` | enum \| absent | an INFO annotation — the only defined value is `not-installed` (§3.1) |
| `message` | string | human-readable detail; controlled vocabulary, never store content |
| `fix` | string \| absent | remediation hint (advice text only — §8) |

Ladder semantics (normative):

- Rungs evaluate **in order**: `present` → `readable` → `schema` →
  `sane`. A **FAIL stops the ladder** — remaining rungs emit nothing.
- WARN never stops the ladder: a `schema-old` store still gets its `sane`
  rung.
- A rung with nothing to evaluate emits **no finding** — an empty dir has
  no first line to parse, a zero-byte file has no version marker; `sane`
  owns the "empty" verdicts.
- **Absence is not breakage.** An uninstalled agent is a valid
  environment: when no candidate root exists, `present` emits a PASS
  finding annotated `note: not-installed` and the ladder stops. §6 groups
  these surfaces under "not detected" — never under failures.

## 3. The rungs (normative)

### 3.1 `present` — do the expected store roots exist?

Probe the surface's candidate roots (SESSION-SURFACES §6, first-existing
or merged as there specified) and its store artifacts:

- No candidate root exists → `PASS`, `note: not-installed`. Ladder stops.
- ≥1 root exists but **none holds a store anchor** → `WARN`
  `store-missing` ("partial or removed install"). Ladder stops — there
  is nothing to open.
- ≥1 anchor exists → `PASS`.

"Anchor" is the per-surface located store of §4 — a store file
(`cli/sessions.db`, `state_*.sqlite`) **or** a store container directory
(`acp-messages/`, `session-state/`, `history-session-state/`,
`chatSessions/`): an existing container is already the install trace;
whether it holds anything is `sane`'s verdict, not `present`'s.

### 3.2 `readable` — does the store open read-only, in the expected format?

- SQLite stores: the file opens `mode=ro` and its first 16 bytes are the
  magic `SQLite format 3\x00` **(verified)**.
- JSONL stores (`events.jsonl`, rollouts, `*.jsonl` mutation logs): the
  first non-empty line parses as JSON. A malformed **tail** is not
  corruption — SESSION-SURFACES `truncated-tail` is a session-parse
  concern; `readable` only proves the store opens.
- JSON snapshots (`chatSessions/*.json`): the whole document parses.
- Directory stores: the directory lists and ≥1 artifact inside it passes
  its own check.

Any present, non-empty artifact that fails its format check → `FAIL`
`store-corrupt`. An OS-level open/list failure (permissions, IO) → `FAIL`
`unreadable`. Either FAIL stops the ladder. A zero-byte artifact is
skipped here — it is not corruption; `sane` owns it.

### 3.3 `schema` — is the version/shape one we know?

Compare the store's version marker (§4) against the known set:

- Known → `PASS`.
- Version **below** the known floor → `WARN` `schema-old` ("migrations
  pending"). Only surfaces with a version ordering can produce this.
- Version **above** the known maximum, or a readable store whose
  expected structure is absent → `WARN` `schema-unknown` ("probably a
  newer agent version — update the doctor, not the store").

### 3.4 `sane` — non-empty, plausibly used?

- A store file that exists but is **zero bytes** → `WARN` `empty-store`
  ("installed but unused").
- A store directory/container that exists but holds **no artifacts** →
  `WARN` `store-empty` ("installed but unused").
- Where counts are cheaply available (row `COUNT(*)`, file globs — §4),
  a store with **zero** sessions/messages → `WARN` `store-empty`.
- Otherwise → `PASS`.

## 4. Per-surface layout — what each rung inspects

`<data>`/`<config>`/`<home>` are the SESSION-SURFACES §6 platform roots;
the corpus (§7) mirrors them as fixture-relative paths.

### 4.1 `devin-cli` — `<data>/devin/cli/sessions.db`

- present: `devin/` root + the db file.
- readable/schema: SQLite magic; version marker is
  `MAX(refinery_schema_history.version)` — `app_state.schema_compat_version`
  mirrors it (SCHEMA.md §1). **`PRAGMA user_version` is not the schema
  version** (it is 0 on real stores); a missing ledger table is
  `schema-unknown`, never `schema-old`.
- known set: **v15–v17** (`MIN_SUPPORTED_SCHEMA`..`LATEST_KNOWN_SCHEMA`,
  verified). `< 15` → `schema-old`; `> 17` → `schema-unknown`.
- sane: `COUNT(*)` on `sessions` > 0.

### 4.2 `devin-chat` — `<config>/Devin/User/acp-messages/<uuid>.db`

- present: the `Devin` (or legacy lowercase `devin`) config root holding
  the `User/acp-messages/` container.
- readable: each `.db` inside passes SQLite magic.
- schema: per db, `meta` + `messages` tables present → `PASS`
  (`acp-v0` shape — SESSION-SURFACES §6.2); missing → `schema-unknown`.
- sane: ≥1 `.db` present (a present-but-empty `acp-messages/` dir →
  `store-empty`; a zero-byte `.db` → `empty-store`).

### 4.3 `copilot-cli` — `<home>/.copilot/` (+ `$COPILOT_DIR`/`$COPILOT_HOME`)

- present: the root holding a `session-state/` or
  `history-session-state/` container (§6.3 layouts).
- readable: every `events.jsonl`/flat file's first line parses.
- schema: the first record is an object carrying the verified envelope
  `{id, parentId, timestamp, type, data}` → `PASS`; valid JSON missing
  the envelope → `schema-unknown`.
- sane: ≥1 session artifact (a present-but-empty `session-state/` →
  `store-empty`).

### 4.4 `codex-cli` — `<home>/.codex/` (+ `$CODEX_HOME`)

- present: the root holding a `state_*.sqlite` file or a
  `sessions/`/`archived_sessions/` rollout container.
- readable: the selected `state_<N>.sqlite` (largest N, §6.4) passes
  SQLite magic; rollout JSONL first lines parse.
- schema: `N` numeric **and** a `threads` table present → `PASS`
  (`state-<N>`); a non-numeric suffix or a readable db without `threads`
  → `schema-unknown`. N is not upper-bounded — a *larger* N is the
  update path, not unknown.
- sane: `COUNT(*)` on `threads` > 0, or ≥1 rollout file.

### 4.5 `vscode-chat` — `<config>/Code[ - Insiders]/User/…`

- present: a variant root holding a `workspaceStorage/*/chatSessions/`
  or `globalStorage/{emptyWindow,transferred}ChatSessions/` container
  (§6.5).
- readable: `.json` docs parse whole; `.jsonl` mutation logs' first line
  parses.
- schema: snapshot docs carry `requests` (or another §6.5 recognizable
  key) → `PASS`; mutation-log kinds ⊆ `{0,1,2,3}` → `PASS`; a parsed doc
  with no recognizable keys, or a log of unknown kinds →
  `schema-unknown`.
- sane: ≥1 chat-session file (a present-but-empty `chatSessions/` →
  `store-empty`).

## 5. Finding vocabulary — closed set

WARN/FAIL findings carry a `code` drawn **only** from:

| code | rung | status | meaning |
|---|---|---|---|
| `store-missing` | present | WARN | roots exist, no store artifact — partial/removed install |
| `store-corrupt` | readable | FAIL | non-empty artifact fails its format check (bad SQLite magic, unparsable first line) |
| `unreadable` | readable | FAIL | OS-level open/list failure (permissions, IO) |
| `schema-old` | schema | WARN | version below the known floor — migrations pending |
| `schema-unknown` | schema | WARN | newer/unrecognized version or structure — probably a newer agent |
| `empty-store` | sane | WARN | store file exists but is zero bytes — installed but unused |
| `store-empty` | sane | WARN | store container holds nothing countable — installed but unused |

INFO notes (PASS-level, not finding codes): `not-installed`.

Where a surface-health concept overlaps SESSION-SURFACES result states
(`source-not-found` ↔ `not-installed`, `read-error` ↔ `unreadable`/
`store-corrupt`, `unsupported-format` ↔ `schema-unknown`), implementations
reuse the **names above** — the health ladder is its own vocabulary; a
finding is not a parse result. The set grows only by deliberate addition
to this document, like the §1 surface set.

## 6. CLI/report contract

- The report carries **one section per surface**, ordered as the §1 set.
  Each section lists findings in ladder order; rungs that emitted nothing
  are not shown.
- `--surface <name>` scopes the run to one surface (repeatable); other
  surfaces are skipped entirely, not reported as absent.
- Surfaces whose only finding is `present`/`not-installed` group under a
  **"not detected"** heading — visibly separate from failures. Absent
  agents never count as broken.
- Suggested exit status: non-zero when any `FAIL` finding exists
  (`store-corrupt`, `unreadable`); WARN-only runs exit 0 — warnings
  inform, they do not gate.

## 7. Install-state corpus — `fixtures/install-states/`

Sibling of `fixtures/session-corpus/`, same vendored-artifact discipline:

- **Generated, never hand-edited** —
  `python -m devin_internals.install_states fixtures/install-states`
  rewrites the tree wholesale. Fixture stores are *minimal*: only what
  each check needs to see (a sqlite with the right tables/ledger, a tiny
  jsonl/json, an empty file, an empty dir).
- Each fixture dir is a **root surrogate** holding one surface's
  §6-relative store layout (`devin/cli/sessions.db`,
  `Devin/User/acp-messages/*.db`, `.copilot/session-state/…`,
  `.codex/state_*.sqlite`, `Code/User/workspaceStorage/*/chatSessions/…`),
  so an absent fixture is an empty dir plus `.gitkeep` — no candidate
  root.
- The corpus carries its own `.gitattributes` (LF-canonical text, binary
  `*.sqlite`/`*.db`) and `.gitignore` (`!*.db` — synthetic stores are
  vendored against the repo-level `*.db` ignore), same self-contained
  discipline as `fixtures/session-corpus/`.
- `install-states-manifest.json` (version 1): per fixture
  `{surface, state, store_path, expected_findings}` where each expected
  finding is `{check, status}` plus `code`/`note` when the §2 fields
  apply. `expected` is what a conformant doctor **must** report.
- `tests/test_install_states.py` re-derives the expected findings from
  the generated bytes (same drift posture as
  `test_evidence_manifest_matches_artifacts`) and byte-compares the
  committed corpus against a fresh build — logical `iterdump` for valid
  sqlite artifacts, bytes for the rest.
- States modeled: `healthy`, `absent`, `missing-store`, `empty-store`,
  `corrupt-store`, `schema-old`, `schema-unknown`. **`locked-or-unreadable`
  is deliberately unmodeled**: POSIX mode bits are advisory or ignored on
  Windows runners and OS/SQLite locks are timing-dependent — no
  deterministic fixture exists.

## 8. Explicit non-scope

- No session parsing — the ladder never produces `SessionMeta` or
  evidence; a `sane` count is a `COUNT(*)`, not a row read.
- No fix execution — `fix` is advice text; the doctor never repairs,
  migrates, or deletes a store.
- No live-agent probing (processes, sockets, network calls, `which`) —
  health is read from installation state alone.
- Global environment checks (disk, permissions, PATH, config syntax) —
  the doctor's own tool-agnostic sections, not per-surface findings.
