# SCHEMA.md — Devin local stores, field by field

Reference for the three local stores. **Verified against schema v20**
(`sessions.db` migration ledger) — a live v20 store was field-inspected on
2026-10-26: migrations 18–20 are all additive (`tool_call_state.source_node_ids`
in 18, `message_search` FTS5 in 19, `live_row_times` in 20) and every column
the spec reads is unchanged in name and type, so the v17 field map below
still applies and v20 is the newest *verified* layout (§4). Unless marked
otherwise, every field below was observed in the live DDL (`sqlite_master` +
`PRAGMA table_info`) — *structure only; row content is never published*.

Marks: **(verified in v17)** = column exists in the v17 DDL · **(unstable)** =
exists but inner format is opaque/unverified — treat as opaque.

## 1. `cli/sessions.db` (schema v17)

Migration ledger (`refinery_schema_history`) holds 17 rows in verified v17
stores; an 18th row exists in the devin-dream D06 drift artifact (real
migration name/DDL uninspected — §4). The detector uses `MAX(version)` as
the schema version and accepts 1–18. `app_state.schema_compat_version`
mirrors it. `PRAGMA user_version` is 0 — it is *not* the schema version.

### ER diagram

```
sessions (id PK)
   │ 1
   │
   │ *            *               *                *               *
   ├──< message_nodes      tool_call_state    rendered_commits  prompt_history
   │      (session_id FK,     (session_id FK,   (session_id FK,   (session_id
   │       node_id,            tool_call_id,     sequence_number,   — no FK,
   │       parent_node_id      tool_call_json,   rendered_html)     timestamp,
   │        → self)            tool_call_update_)                    is_shell)
   │
   │ *            *                  (standalone)        (standalone)
   └──< subagent_heads          app_state           refinery_schema_history
          (session_id FK,        key PK,              version PK,
           agent_id,             value)               name, applied_on,
           chain_node_id,                             checksum
           updated_at)

sqlite_sequence — AUTOINCREMENT bookkeeping (row_id/id columns)
```

Explicit indexes (v17): `idx_sessions_activity` (`last_activity_at DESC`),
`idx_sessions_hidden` (`hidden`), `idx_message_nodes_session` (`session_id`),
`idx_prompt_history_session` + `idx_prompt_history_timestamp`
(`timestamp DESC`), `idx_rendered_commits_session`
(`session_id, sequence_number`).

### `sessions` — one row per CLI session

| column | type | null | notes |
|---|---|---|---|
| `id` | TEXT PK | — | session identifier (UUID-shaped) **(verified in v17)** |
| `working_directory` | TEXT | NOT NULL | cwd the session runs in |
| `backend_type` | TEXT | NOT NULL | execution backend label **(unstable values)** |
| `model` | TEXT | NOT NULL | model name |
| `agent_mode` | TEXT | NOT NULL | mode label **(unstable values)** |
| `created_at` | INTEGER | NOT NULL | epoch **ms** (Windows-verified); Linux v17 stores observed in epoch **seconds** — readers discriminate by `< 1e12` (see `SESSION-SURFACES.md` §6.1) |
| `last_activity_at` | INTEGER | NOT NULL | epoch ms; drives `idx_sessions_activity`; same platform magnitude caveat as `created_at` |
| `title` | TEXT | yes | human title; NULL until set |
| `main_chain_id` | INTEGER | yes | head node of the main message chain |
| `shell_last_seen_index` | INTEGER | yes, DEFAULT 0 | shell-output cursor |
| `cogs_json` | TEXT | yes | JSON **(unstable)** |
| `workspace_dirs` | TEXT | yes | JSON array of dirs **(unstable)** |
| `hidden` | INTEGER | NOT NULL, DEFAULT 0 | boolean 0/1 |
| `metadata` | TEXT | yes | JSON **(unstable)** |

### `message_nodes` — message forest per session

| column | type | null | notes |
|---|---|---|---|
| `row_id` | INTEGER PK AUTOINCREMENT | — | physical row id |
| `session_id` | TEXT | NOT NULL | FK → `sessions.id` |
| `node_id` | INTEGER | NOT NULL | node id within the session's forest; `UNIQUE(session_id, node_id)` |
| `parent_node_id` | INTEGER | yes | NULL on roots; self-references `node_id` |
| `chat_message` | TEXT | NOT NULL | serialized message **(unstable — opaque payload)** |
| `created_at` | INTEGER | NOT NULL | epoch ms |
| `metadata` | TEXT | yes | JSON **(unstable)** |

### `tool_call_state` — persisted ACP tool calls

| column | type | null | notes |
|---|---|---|---|
| `session_id` | TEXT | NOT NULL | FK → `sessions.id`; part of `PK(session_id, tool_call_id)` |
| `tool_call_id` | TEXT | NOT NULL | part of PK |
| `tool_call_json` | TEXT | yes | serialized `acp::ToolCall` **(unstable)**; NULL when the call was interrupted before commit |
| `tool_call_update_json` | TEXT | yes | serialized `acp::ToolCallUpdate` **(unstable)** |

### `prompt_history` — prompt recall buffer

| column | type | null | notes |
|---|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | — | |
| `content` | TEXT | NOT NULL | prompt text **(unstable — may contain user content; parsers must not dump)** |
| `timestamp` | INTEGER | NOT NULL | epoch ms; `idx_prompt_history_timestamp` |
| `session_id` | TEXT | NOT NULL | **no declared FK** |
| `is_shell` | INTEGER | NOT NULL, DEFAULT 0 | boolean 0/1 (shell command vs prompt) |

### `rendered_commits` — rendered HTML snapshots

| column | type | null | notes |
|---|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | — | |
| `session_id` | TEXT | NOT NULL | FK → `sessions.id`; `UNIQUE(session_id, sequence_number)` |
| `sequence_number` | INTEGER | NOT NULL | ordering within session |
| `rendered_html` | TEXT | NOT NULL | HTML payload **(unstable)** |
| `created_at` | INTEGER | NOT NULL | epoch ms |

### `subagent_heads` — subagent chain cursors

| column | type | null | notes |
|---|---|---|---|
| `session_id` | TEXT | NOT NULL | FK → `sessions.id`; part of `PK(session_id, agent_id)` |
| `agent_id` | TEXT | NOT NULL | part of PK |
| `chain_node_id` | INTEGER | NOT NULL | last seen node in that subagent's chain |
| `updated_at` | INTEGER | NOT NULL | epoch ms |

### `app_state` — CLI key/value state

| column | type | null | notes |
|---|---|---|---|
| `key` | TEXT PK | NOT NULL | e.g. `schema_compat_version` |
| `value` | TEXT | NOT NULL | |

### `refinery_schema_history` — migration ledger

| column | type | null | notes |
|---|---|---|---|
| `version` | int4 PK | — | monotonically increasing; `MAX(version)` = schema version |
| `name` | VARCHAR(255) | yes | migration name |
| `applied_on` | VARCHAR(255) | yes | date string |
| `checksum` | VARCHAR(255) | yes | migration checksum |

## 2. `User/acp-messages/<session-uuid>.db` — Devin Desktop, per GUI session

| table | columns | notes |
|---|---|---|
| `meta` | `key` TEXT PK, `value` TEXT NOT NULL | session-level metadata; **key space is open — undeclared keys are tolerated** (the `_meta` fixtures below pin the verified keys per store version) |
| `messages` | `position` INTEGER PK, `kind` TEXT NOT NULL, `payload` TEXT NOT NULL | ordered ACP message log; payload *shape* is versioned by `meta.schema_version` — see the message-schema corpus below |

No migration ledger exists here — the parser gates on table shape
(`meta` + `messages` present). **(table shape verified 2026-09-29 across
2 DBs; payload/meta shape census 2026-10-27 across 36 DBs — 2 v1, 34 v6)**

### Message payload shapes — `fixtures/message-schemas/` (executable)

The JSON inside `messages.payload` was opaque until 2026-10-27, when a
shape census of 36 live stores (field names and JSON types only — never
values) produced the versioned fixture corpus under
`fixtures/message-schemas/` (also packaged as
`devin_internals/corpus/message-schemas/`). One fixture per
(`messages.kind`, `meta.schema_version`) pair, plus a `_meta` fixture
per store version for the `meta` table itself. The fixture format and
verification semantics are documented in
`fixtures/message-schemas/README.md` and enforced by
`src/devin_internals/message_schemas.py` +
`tests/test_message_schemas.py`.

**Field marks** — every declared field is either `verified` (observed in
real captured stores; *asserted* by `verify_db` — a store that
contradicts one fails loudly) or `unverified` (documented in the
evidence or in a sibling fixture for another store version, never
confirmed — *never asserted*; observing one is reported as a promotion
candidate). A real store contradicting a verified claim is the drift
detector doing its job: demote the mark honestly rather than suppress
the failure.

**Versioned kind vocabulary** (verified by census):

| `meta.schema_version` | observed `messages.kind` |
|---|---|
| `1` | `user_message`, `agent_message`, `agent_thought`, `tool_call` |
| `6` | those four + `plan`, `subagent` (v6 additions — never observed under v1) |

`tool_call_update` stays **documented-only** (SESSION-EVIDENCE.md §6.2
lists it in the session-update vocabulary): it carries `unverified`
fixtures under both versions and was absent from all 36 sampled stores —
a real sighting reports a promotion, never a failure.

**Store-level invariants** (verified, `store_checks` on the `_meta`
fixtures): `meta.message_count` (TEXT integer) equals the `messages`
row count, and `messages.position` is a contiguous 0-based sequence —
true on all 36 sampled stores.

**Run it:** `python -m devin_internals.message_schemas verify <db|dir>`
(exit 1 on contradictions, graded notes otherwise) and
`... extract <db>` (prints a store's aggregated shape — an authoring
aid; values are never recorded).

**Still open/unverified:** the `meta` key space itself (extra keys are
`extra_meta_keys` notes, never contradictions); `cognition.ai/*` `_meta`
namespaces and `content.rawInput` argument spaces (`open` — declared
children are asserted, undeclared ones tolerated);
`subagent.childMessages[]` recursion (open); open vocabularies such as
`warnings[].level` and `content.status` beyond their observed values
(`closed` only where the upstream enum is fully documented);
`plan`/`subagent` under v1 are contradictions *by absence of observed
evidence*, not by proof of impossibility.

## 3. `User/globalStorage/state.vscdb` — VS Code-style KV store

| table | columns | notes |
|---|---|---|
| `ItemTable` | `key` TEXT UNIQUE ON CONFLICT REPLACE, `value` BLOB | `PRAGMA user_version = 1`; Devin-relevant keys live under `windsurfSpace.*` |

`value` is declared BLOB but holds text in practice — the parser decodes
UTF-8 with `errors="replace"`. Individual `windsurfSpace.*` key names are
**not published** (key names are row content); use
`StateVscdbStore.list_prefix()` to enumerate at runtime.

## 4. Known gaps (explicit)

- **v18–v20 DDL**: a live v20 store was field-inspected on 2026-10-26 —
  all three migrations are additive and none touches a column the spec
  reads: 18 `tool_call_state_source_nodes` adds `tool_call_state.source_node_ids
  TEXT`, 19 `add_message_search` adds `CREATE VIRTUAL TABLE message_search
  USING fts5(content, content='', contentless_delete=1, tokenize='unicode61')`,
  20 `live_row_times` adds `CREATE TABLE live_row_times (session_id TEXT NOT
  NULL, row_key TEXT NOT NULL, started_at TEXT NOT NULL, PRIMARY KEY
  (session_id, row_key))`. `VERIFIED_SCHEMA` is therefore 20; `> 20` still
  raises `UnknownSchemaVersionError`. The vendored
  `fixtures/schema-versions/sessions-v18.db` / `sessions-v19.db` (devin-dream
  D06 drift canaries, synthetic ledger rows) now pin in-range detection —
  `verified` reports `False` for both, since neither is the newest
  inspected layout.
- **v15/v16 DDL**: only v17's base DDL plus the additive v18–v20 deltas
  were inspected. The real migration list (names/deltas) lives in
  `refinery_schema_history` *rows*, which are row content and were not
  read. Fixtures therefore model the v17 layout plus the inspected deltas —
  for versions above the newest delta the `schema_version` knob still
  fakes the ledger marker, not a layout. Documented gap, not a guess —
  fill in when old-DB evidence is available.
- **JSON/text payload columns** (`chat_message`, `metadata`, `cogs_json`,
  `workspace_dirs`, `tool_call_*_json`, `rendered_html`,
  `ItemTable.value` semantics): column exists (verified) but the inner format
  is opaque — **unstable**. Do not build on their inner structure without
  fresh evidence. **Exception:** acp `messages.payload` is no longer fully
  opaque — the verified subset of its per-(kind, version) shape lives in
  `fixtures/message-schemas/` (§2); everything outside the declared
  verified fields remains unstable.
- **`session_locks/`**, `skill_events_spool.lock`, `sessions.db-wal` siblings:
  observed on disk, not yet spec'd.
