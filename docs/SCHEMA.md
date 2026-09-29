# SCHEMA.md — Devin local stores, field by field

Reference for the three local stores. **Verified against schema v17**
(`sessions.db` migration ledger) on 2026-09-29, Windows. Unless marked
otherwise, every field below was observed in the live DDL (`sqlite_master` +
`PRAGMA table_info`) — *structure only; row content is never published*.

Marks: **(verified in v17)** = column exists in the v17 DDL · **(unstable)** =
exists but inner format is opaque/unverified — treat as opaque.

## 1. `cli/sessions.db` (schema v17)

Migration ledger (`refinery_schema_history`) holds 17 rows; the detector uses
`MAX(version)` as the schema version. `app_state.schema_compat_version`
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
| `created_at` | INTEGER | NOT NULL | epoch **ms** |
| `last_activity_at` | INTEGER | NOT NULL | epoch ms; drives `idx_sessions_activity` |
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
| `meta` | `key` TEXT PK, `value` TEXT NOT NULL | session-level metadata; **key space is open — not enumerated** (values are row content) |
| `messages` | `position` INTEGER PK, `kind` TEXT NOT NULL, `payload` TEXT NOT NULL | ordered ACP message log; `kind`/`payload` formats **(unstable)** |

No migration ledger exists here — the parser gates on table shape
(`meta` + `messages` present). **(both verified 2026-09-29 across 2 DBs)**

## 3. `User/globalStorage/state.vscdb` — VS Code-style KV store

| table | columns | notes |
|---|---|---|
| `ItemTable` | `key` TEXT UNIQUE ON CONFLICT REPLACE, `value` BLOB | `PRAGMA user_version = 1`; Devin-relevant keys live under `windsurfSpace.*` |

`value` is declared BLOB but holds text in practice — the parser decodes
UTF-8 with `errors="replace"`. Individual `windsurfSpace.*` key names are
**not published** (key names are row content); use
`StateVscdbStore.list_prefix()` to enumerate at runtime.

## 4. Known gaps (explicit)

- **v15/v16 DDL**: only v17's DDL was inspected. The real migration list
  (names/deltas) lives in `refinery_schema_history` *rows*, which are row
  content and were not read. Fixtures therefore model **v17 only**; the
  `schema_version` knob fakes the ledger marker, not the layout. Documented
  gap, not a guess — fill in when old-DB evidence is available.
- **JSON/text payload columns** (`chat_message`, `metadata`, `cogs_json`,
  `workspace_dirs`, `tool_call_*_json`, `rendered_html`, acp `payload`,
  `ItemTable.value` semantics): column exists (verified) but the inner format
  is opaque — **unstable**. Do not build on their inner structure without
  fresh evidence.
- **`session_locks/`**, `skill_events_spool.lock`, `sessions.db-wal` siblings:
  observed on disk, not yet spec'd.
