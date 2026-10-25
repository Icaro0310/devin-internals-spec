# SCHEMA-VERSIONS.md — store schema drift matrix across Devin releases

The contract boundary is the moat: every store below is undocumented upstream
and its schema **changes without notice**. This ledger tracks, per store, the
version marker, the latest version we have verified field-by-field, and the
release it first landed in — so a new Devin build that bumps a schema is
visible here (and to `detect_schema_version()`) instead of silently
corrupting reads.

Marks: **(verified)** = inspected live, field-level, on the date in the
evidence column · **(gated)** = no version marker exists, the parser gates on
table shape · **(unverified)** = observed, not yet inspected.

## 1. `cli/sessions.db` — `refinery_schema_history` ledger

The schema version is `MAX(version)` in `refinery_schema_history`.
`PRAGMA user_version` is **0** and is *not* the schema version.
`app_state.schema_compat_version` exists but was observed as `"0"` on a live
v17 install (2026-10-22, Linux) — it does **not** reliably mirror
`MAX(version)`; the ledger is the marker of record.

Supported range: `MIN_SUPPORTED_SCHEMA..LATEST_KNOWN_SCHEMA` = **15..18**
(`src/devin_internals/schema.py`). Anything outside `1..18` raises
`UnknownSchemaVersionError`; 1..14 open but report `supported: false`.
Known/supported ≠ verified: the detector reports `verified: true` only at
`VERIFIED_SCHEMA` = **17** — v18 is registered as observed drift
(the devin-dream D06 canary fixture below), never field-inspected.

| version | first landed | contents (high level) | evidence |
|---|---|---|---|
| v1–v15 | 2026-05-06 | base schema through `add_hidden_column`-era migrations; field list not published (ledger rows are treated as row content) | release dates recorded in `docs/SPEC.md`; v15 supported, never field-verified |
| v16 | 2026-07-05 | `sessions.metadata` (session JSON metadata column) | inferred from v16→v17 delta; **unverified** at field level |
| v17 | 2026-09-14 | `subagent_heads` table + `prompt_history` indexes; full field-by-field spec in `docs/SCHEMA.md` | **(verified)** 2026-09-29 Windows, re-verified live 2026-10-22 Linux (17 ledger rows) |
| v18 | drift fixture | ledger row `18` observed in the devin-dream D06 *schema-drift canary* `sessions.db`; inner layout not field-inspected | **(observed drift, unverified)** — `fixtures/schema-versions/sessions-v18.db` vendored byte-verbatim from devin-assure's golden corpus, sha256-pinned in `manifest.json`; `LATEST_KNOWN_SCHEMA` accepts it, `VERIFIED_SCHEMA` stays 17 |

### Ledger-semantics caveats (verified live, 2026-10-22)

- `applied_on` records when **this install** applied the migration — a fresh
  install replays all 17 migrations in one batch (all rows share the install
  timestamp), so `applied_on` is an *install* timestamp, not a *release*
  timestamp. Release dates in the table above come from repo history, not
  from the ledger.
- The migration `name` column exists but row contents are not published
  (see `docs/SCHEMA.md` §4) — the version *numbers* and count are the
  contract surface.

## 2. `User/acp-messages/<session-uuid>.db` — no version marker

| store | marker | latest known | evidence |
|---|---|---|---|
| `acp-messages/*.db` | none — gated on table shape (`meta` + `messages` present) | shape as spec'd in `docs/SCHEMA.md` §2 | **(gated, verified)** 2026-09-29 across 2 DBs; still present 2026-10-22 |

If Cognition adds a version key or a third table, the gate fails loudly the
next time a DB is opened — that is the intended drift signal.

## 3. `User/globalStorage/state.vscdb` — `PRAGMA user_version`

| store | marker | latest known | evidence |
|---|---|---|---|
| `state.vscdb` | `PRAGMA user_version` | **1** | **(verified)** 2026-10-22 Linux; single `ItemTable`, `windsurfSpace.*` keys |

No migration ledger; `ItemTable` shape is the gate. Key names are row content
and are not enumerated in the spec.

## 4. Drift protocol — what to do when a version moves

1. `detect_schema_version()` raises `UnknownSchemaVersionError` on the new
   version — that failure **is** the signal; do not silence it.
2. Inspect the new DDL (`sqlite_master` + `PRAGMA table_info`), diff against
   `docs/SCHEMA.md`, and mark each changed field with its version tag.
3. Bump `LATEST_KNOWN_SCHEMA` in `src/devin_internals/schema.py` only after
   field-level verification; add a `schema_version=N` fixture row in
   `fixtures.py` and regenerate corpus fixtures that stamp a version.
4. Record the new row in the §1 matrix with its release date and evidence.
5. CHANGELOG entry; the version bump and the doc update land in the same PR.

## 5. Known gaps (explicit)

- **v1–v15 field deltas**: the ledger rows were never read for content; the
  v16 row above is inferred from the v16→v17 diff, not verified. Fill in when
  old-DB evidence is available — same documented gap as `docs/SCHEMA.md` §4.
- **Release ↔ version mapping**: release dates (2026-05-06, 2026-07-05,
  2026-09-14) are the dates each schema was first observed on a real install,
  not vendor version numbers — Devin does not publish a CLI changelog with
  schema annotations.
- **Desktop-only surfaces** (`session_locks/`, `skill_events_spool.lock`,
  `sessions.db-wal`/`shm` siblings, `heartbeat/`): observed on disk, carry no
  version marker, not yet spec'd.
