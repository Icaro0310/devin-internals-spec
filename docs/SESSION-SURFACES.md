# SESSION-SURFACES.md — canonical spec for multi-agent session sources

The contract for reading **any agent's** local session store into the shared
canonical metadata model. Two implementations consume this spec:

- **agent-sessions** (TypeScript, `packages/agent-sessions/src/sources/*.ts`) —
  live metadata listing for the session browser. Reads sources on every
  refresh; no persistence.
- **devin-search collectors** (Python) — incremental index over the same
  sources for full-text search.

**Rule: implement from this document, never from the other implementation's
code.** When the two sides disagree, the bug is in whichever side diverges
from this text — and the text, once corrected, is updated in the same PR as
the fix. Semantics that exist only in one implementation are the drift this
document exists to prevent (D-2026-10-15).

Marks: **(verified)** = observed in a real store · **(unstable)** = format
opaque/unverified — treat as opaque.

---

## 1. Surface vocabulary — closed set

`<product>-<interaction-mode>` — product names the agent, the suffix names
how the user talks to it, not a category of app. The set grows only by
deliberate addition to this document *and* the `Surface` union in
`agent-sessions/src/model.ts`, in the same PR.

| surface | product | interaction | backing store |
|---|---|---|---|
| `vscode-chat` | VS Code | chat panel | `chatSessions/*.json{,l}` |
| `copilot-cli` | GitHub Copilot | terminal CLI | `session-state/<uuid>/events.jsonl` (+flat/legacy) |
| `codex-cli` | OpenAI Codex | terminal CLI | `state_<N>.sqlite` + rollout JSONL |
| `devin-cli` | Devin | terminal CLI | `cli/sessions.db` (schema v15–v17+) |
| `devin-chat` | Devin Desktop | chat panel | `User/acp-messages/<uuid>.db` |

`devin-chat` parallels `vscode-chat` deliberately: Devin Desktop is a VS Code
fork, so the two are the same interaction mode in sibling products. A future
GUI panel for a CLI product gets `<product>-chat` — the axis already holds.

## 2. Canonical model — what every parser emits

One `SessionMeta` per session:

| field | type | contract |
|---|---|---|
| `surface` | enum §1 | never outside the closed set |
| `id` | string \| null | canonical ID (§4); null when workspace identity is unstable → `unknown-workspace` warning, never deduplicated |
| `display_key` | string | `id ?? <surface>:ephemeral:<index>` — in-memory only |
| `title` | null | **always null.** Stored titles are auto-derived from message content — content-derived, not metadata. Not a bug; do not "fix". |
| `started_at` | ISO 8601 \| null | session creation timestamp |
| `ended_at` | ISO 8601 \| null | §5 — never guessed |
| `source_version` | string \| null | store's own version marker, per surface (§6) |
| `workspace_hash` | string \| null | sha256(normalized workspace seed)[:16] — the path itself is never emitted |
| `event_count` | int \| null | count of message/event rows when cheaply available |
| `parse_warnings` | list | controlled-template messages only: codes + counts, never paths, titles, ids, or content |

Result states: `ok` · `partial` · `no-sessions` · `source-not-found` ·
`unsupported-format` · `read-error`.

## 3. Read contract — all surfaces

- **Read-only.** SQLite opens `mode=ro` (retry with `immutable=1`); files are
  read, never written. A constructed-but-failed SQLite handle is `close()`d
  before retry — leaks accumulate one per refresh otherwise.
- **Metadata columns only.** Columns that hold content (`chat_message`,
  `title`, `metadata` JSON, `payload`, message bodies) are never selected.
- **One broken surface never blocks the others** — a throwing parser degrades
  to `read-error` for its surface only.
- **Hidden rows are skipped** where the store marks user-hidden state
  (`sessions.hidden=1` in `devin-cli`) — same convention as the history
  export: hidden is the user's signal, not a parse failure.
- **`workspace_hash` seed normalization:** absolute path, resolved as the
  platform allows, trailing separators stripped, case per platform. The hash
  is not reversible and never contains the path.

## 4. Canonical ID

```
<surface>:<workspace-hash>:<kind>:<value>   (hash present)
<surface>:<kind>:<value>                    (hash absent)
```

`kind ∈ {native, documented-alt, provisional-hash}`. Components encode `%`
then `:` so separators are unambiguous. **Dedup scope: same surface + same
workspace hash only.** Records without workspace identity are never
deduplicated and never claim canonical uniqueness; the same native id seen in
*two different* workspaces is a `cross-workspace-duplicate` warning, not a
merge.

## 5. `ended_at` — the inference chain (normative)

Session stores rarely mark "closed". Apply **in this order**, per session:

1. **Explicit close marker wins** — a `session.shutdown`/task-complete-style
   event in the store is `ended_at` directly, no warning.
2. **Fresh activity → `session-open`** — last activity within **60 s** of
   read time: `ended_at = null` + `session-open` warning. Never infer a
   close over fresh data.
3. **Stale activity → inferred close** — `ended_at = last activity
   timestamp` + `no-end-marker` warning ("closed state inferred from last
   activity"). The warning is mandatory: an inferred close is not evidence
   of one.
4. **No activity timestamp** — `ended_at = null` + `no-end-marker` warning
   ("no activity timestamp").

Both implementations emit the identical chain and the identical warning
codes. A Python collector that skips the warning is non-conformant even if
the timestamp matches.

## 6. Per-surface layout

### 6.1 `devin-cli` — `cli/sessions.db` **(verified, schema v17)**

Candidates, first existing wins (same roots as `devin-search/paths.py`):

| platform | `<root>` candidates (db at `<root>/devin/cli/sessions.db`) |
|---|---|
| win32 | `%APPDATA%`, else `~/AppData/Roaming` |
| darwin | `~/Library/Application Support` |
| linux | `$XDG_DATA_HOME` else `~/.local/share` → `$XDG_CONFIG_HOME` else `~/.config` → `~/` |

- `sessions`: `id`→native id; `working_directory`→workspace seed;
  `created_at`, `last_activity_at` (epoch **seconds**)→timestamps;
  `hidden=1`→skip. `title`, `metadata`, `cogs_json`, `workspace_dirs` never
  selected.
- `message_nodes`: `COUNT(*) GROUP BY session_id` → `event_count` (absent in
  old schemas → null).
- `source_version`: `schema-v<MAX(version)>` from `refinery_schema_history`;
  `sessions.db` when the ledger is absent. `PRAGMA user_version` is **not**
  the schema version.
- Full field reference: `SCHEMA.md` §1.

### 6.2 `devin-chat` — `User/acp-messages/<session-uuid>.db` **(verified across 2 DBs)**

Candidate dirs, first existing wins (mirrors `paths.py` `acp_dir_candidates`):

| platform | candidates (`<dir>/<session-uuid>.db`) |
|---|---|
| win32 | `%APPDATA%/Devin/User/acp-messages`, `~/AppData/Roaming/Devin/User/acp-messages` |
| darwin | `~/Library/Application Support/devin/User/acp-messages` |
| linux | `~/.config/Devin/User/acp-messages`, `~/.config/devin/User/acp-messages`, `~/devin/User/acp-messages` (same for `$XDG_CONFIG_HOME` overrides) |

One file per GUI session; the filename uuid is the native id.

- `meta` (`key`,`value`): session metadata — key space **open**, do not
  enumerate keys that carry content; read only the keys the layout section
  of the ACP parser documents as metadata.
- `messages` (`position`,`kind`,`payload`): ordered ACP log;
  `kind`/`payload` **(unstable)** — count positions for `event_count`,
  never parse payload content for metadata.
- No migration ledger: parser gates on table shape (`meta` + `messages`
  present) → `unsupported-format` otherwise. `source_version`: `acp-v0`
  until a real version marker is observed.
- Full field reference: `SCHEMA.md` §2.

### 6.3 `copilot-cli` — `session-state` **(spec v3.4.4)**

Roots scanned in order, all existing merged: `$COPILOT_DIR`, `$COPILOT_HOME`,
`~/.copilot`. Layouts that may coexist:

- `session-state/<uuid>/{events.jsonl, workspace.yaml}` — primary
- `session-state/<uuid>.jsonl` — flat
- `history-session-state/` — legacy

`events.jsonl` envelope: `{id, parentId, timestamp, type, data}`.
`session.start` gives started_at/native id; workspace from `workspace.yaml`
(git root preferred). `session.shutdown` is the explicit close marker (§5.1).
Unknown event types are pass-through + counted `partial-parse` — never
fatal. A malformed last line is `truncated-tail`; malformed mid-file lines
are `partial-parse`. Same native id in >1 root → `duplicates`
(`cross-workspace-duplicate` when the workspace hash differs); first readable
copy wins. `source_version`: `events-jsonl`.

### 6.4 `codex-cli` — `state_<N>.sqlite` + rollouts **(spec v3.4.4)**

Root: `$CODEX_HOME` else `~/.codex`. Precedence:

1. `state_<N>.sqlite`, largest N wins (read-only `node:sqlite`) →
   `threads` rows: `id`, `created_at`, `updated_at`, `cwd`,
   `has_user_event`. Unreadable → `read-error` if no rollouts, else
   `partial-parse` warning + rollout pass. `source_version`: `state-<N>`.
2. Rollout JSONL under `sessions/`, `archived_sessions/`,
   `$CODEX_SESSIONS_DIR` — `session_meta` records give id/cwd/timestamps;
   `task_started` without matching `task_complete` → `session-open` (a
   later `task_started` invalidates the previous completion marker).
   Forks (`forked_from_id` present) are ignored. Known ids from the state
   db → `duplicates`. `source_version`: `rollout`.

### 6.5 `vscode-chat` — `chatSessions` **(spec v3.4.4)**

`<base>/<Variant>/User/...` where `<base>` = `env.appdata`, else
`AppData/Roaming` (win32), `Library/Application Support` (darwin), `.config`
(linux); `<Variant>` = `Code` and `Code - Insiders` today. Remote:
`~/.vscode-server/data/User/`. (Other forks — VSCodium, Devin, Windsurf —
are not scanned today; adding a variant is a doc+adapter PR, not a config.)

- `workspaceStorage/<wsDir>/chatSessions/<id>.{json,jsonl}` — the `<wsDir>`
  name **is** VS Code's stable workspace hash, used verbatim.
- `globalStorage/{emptyWindow,transferred}ChatSessions/` — workspace_hash
  null (`unknown-workspace` does **not** apply; global is a legitimate
  identity).

A `.json` holds the final snapshot; a `.jsonl` is a mutation log replayed
in order: kind `0` replace document · `1` set at path · `2` append to array
(truncate to index `i` first when given) · `3` delete path. `.jsonl` wins
when both exist; unknown kinds counted; trailing unparseable line →
`truncated-tail`. Recognizable sessions carry ≥1 of `requests`,
`customTitle`, `title`, `creationDate`, `lastMessageDate`, `version`,
`requesterUsername`, `responderUsername`, `sessionId`, `initialLocation`,
`isImported`, `agent`. `source_version`: the doc `version` field when
present, else `chatSessions`.

## 7. Fixture corpus and parity

The parity contract mirrors the `redact` precedent (`test/redact-corpus.jsonl`
shared between the TS port and Python original):

- **One corpus**, generated deterministically (`devin_internals.fixtures`
  for the Devin stores — DDL copied verbatim, rows synthetic, seeded),
  consumed by both test suites. Committed fixture files for the
  non-Devin stores under `fixtures/session-corpus/` with a `manifest.json`
  listing per-fixture expected canonical fields (surface, id shape,
  state, warning codes — never content).
- **Parity test per side**: same fixture → same canonical output on the
  fields the manifest declares. Divergence = spec ambiguity → fix the doc
  and the wrong side, never both sides' behavior independently.
- Fixtures model **current observed layouts**; format drift in a real store
  triggers a fixture + doc + adapter update in one PR.

## 8. Explicit non-scope

- No message content, titles, prompts, or payload bodies — anywhere.
- No live-join between stores (a `devin-cli` session and a `devin-chat`
  session are different sessions; correlation is a later, separate
  contract).
- `state.vscdb`, `session_locks/`, WAL siblings: observed, not spec'd —
  see `SCHEMA.md` §4.
