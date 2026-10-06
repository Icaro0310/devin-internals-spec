# EVIDENCE-EQUIVALENCE.md — local store vs official surfaces

Study of whether the evidence a verifier can extract from the local Devin
stores (`sessions.db` + siblings) is semantically reproducible from the
official surfaces (REST API v3, Devin MCP, DeepWiki MCP). Feeds the future
`devin-qa-pack --source local|api|mcp` adapter decision.

**Date:** 2026-10-06. **Method:** local findings verified against the live
store (`~/.local/share/devin/cli/sessions.db`, schema v17) and
`SESSIONS_DB_DDL_V17`; API findings verified against the published OpenAPI
specs (`docs.devin.ai/{v1,v2,v3}-openapi.yaml`), the `devinai` PyPI wheel
(0.1.0, Stainless-generated), and **live calls with a Personal Access Token
(`cog_`) on a Pro-plan org** — REST `GET`s only, plus one minimal session
created via MCP (`echo`/`touch`/`cat`, then archived) to observe real
`shell` events.

Marks: **(spec)** = in the published OpenAPI document · **(live)** = verified
against a running endpoint · **(sdk)** = in the `devinai` wheel only.

## 1. The equivalence unit

qa-pack does not consume `sessions.db` tables directly. It consumes
`SourceSession` (`adapters/base.py`): `{source, session_id, title,
working_directory, claims, calls: tuple[ParsedToolCall], raw_call_count}`,
where each `ParsedToolCall` normalizes `{kind, commands, status,
search_text, http_statuses}`. Verdicts are computed purely over that shape
(`report.py:audit_source`).

So the study question is precise: **can each surface produce a faithful
`ParsedToolCall` stream plus the `raw_call_count` empty-vs-unreadable
distinction?** Two precedent adapters show the degradation contract:
`aider` emits `status="unknown"` (no exit codes in its history) → claims go
`unverifiable`, never fake `verified`; `claude-code` has real tool-result
blocks → `completed`/`failed`. Equivalence is per-field, not per-surface.

## 2. What each surface exposes

### 2.1 Local store (`sessions.db` v17) — ground truth

| evidence | location | mark |
|---|---|---|
| session id, cwd, model, mode, created/last-activity, workspace_dirs | `sessions.*` | verified v17 |
| message forest (role, content, tool_calls refs, thinking) | `message_nodes.chat_message`, ordered by `node_id`/`created_at` | verified v17 |
| tool invocation: `kind`, `title`, `rawInput` dict, `locations[].path` | `tool_call_state.tool_call_json` (ACP `ToolCall`) | verified live |
| tool outcome: `status`, `content[]` output text, `_meta.terminal_exit.{exit_code,signal}`, `cwd` | `tool_call_state.tool_call_update_json` | verified live |
| tool result as transcript | `message_nodes` `role=tool` rows, joined by `tool_call_id` | verified live |
| per-call timestamps / ordering | **absent** — no timestamp or sequence column in `tool_call_state` | verified live |
| tokens | `message_nodes.metadata.num_tokens_preceding` only | verified |
| ACU / cost | **absent** (`sessions.cogs_json` unstable, unused) | verified |
| schema version | `refinery_schema_history` ledger | verified |

### 2.2 API v3 (published spec) — narrative + metadata

`SessionResponse`: `session_id`, `url`, `status`, `status_detail`, `title`,
`created_at`/`updated_at` (unix int), `acus_consumed`, `devin_mode`,
`origin`, `parent_session_id`, `child_session_ids[]`, `pull_requests[]`,
`structured_output`, `tags[]`, `security_profile`, `user_id`,
`service_user_id`, `playbook_id`, `automation_id`, `category`/`subcategory`
**(spec; `/v3/self` + `GET sessions` confirmed live with PAT)**.

`GET .../sessions/{id}/messages` → `SessionMessage{event_id,
source(devin|user), message(string), created_at, origin, user_id, username}`
**(spec + live)** — flat narrative text; no structured tool payloads.

`GET .../sessions/{id}/insights` → AI-generated `analysis{timeline[],
issues[], classification, skill_usage, note_usage}` **(spec)** — derived
second-order evidence, not raw records.

`GET .../consumption/daily/sessions/{id}` → per-session ACU by date
**(spec)** — a field the local store lacks entirely.

### 2.3 The events surface — real, typed, and MCP-only

The `devinai` SDK implements `GET .../sessions/{id}/events`,
`.../events/details`, `.../events/search` **(sdk)** — but on
`api.devin.ai` all three return **404 (live-verified, PAT)**. The surface
is reachable today **only through the Devin MCP** tool
`devin_session_events` (`action: list|details|search`) **(live)**.

`action=list` → one line per event: `event_id, created_at, direction
(<<< incoming / >>> outgoing), event_type (category), summary`, cursor-
paginated. ~90 `event_type`s in `category` ∈ {`shell`, `file`, `search`,
`browser`, `mcp`, `git`, `message`, `status`, `secret`, `todo`,
`recording`, `knowledge`, `playbook`, `webhook`, `lifecycle`, `other`}.

`action=details` → per event, `contents` is a **typed JSON object whose
shape depends on event_type** — not an opaque blob. Live-verified shapes:

| event_type | contents fields (observed) |
|---|---|
| `shell_process_started` | `command` (full raw string), `chain[]` (parsed sub-commands with `operation{kind,paths}` and `certainly_ran`), `shell_id`, `process_id`, `starting_dir`, `is_major_action` |
| `terminal_update` | `contents` (**base64-encoded stdout chunk**), `shell_id`, `process_id` |
| `shell_process_completed` | `exit_code` (string, e.g. `"0"`), `output_trunc` (truncated output text), `process_id` |
| `devin_message` | `message` (full text) |
| `devin_thoughts` | `message` (thinking text), `thinking_duration_ms` |
| `status_update` | `enum` (`working`/`blocked`/…), `message`, `user_action_required` |
| `acu_consumption_at_last_user_interaction` | `amount`, `overage_amount` |
| `context_growth_update` | `tool_aggregates[]{tool_name,call_count,approx_ant_tokens,total_output_bytes,total_invocation_bytes}`, `current_context_tokens`, `per_source_context_bytes` |
| `initial_user_message`, `iteration_stats`, `iteration_checkpoint`, `live_chain_update`, `repo_setup_initialized`, `plugins_activated`, `shared_file_updated`, `one_line_thoughts`, `is_typing`, `simple_activity_update` | also present in the stream |

This is the closest official analog to `tool_call_state` — and in the
dimensions verified it is **stronger than the local row**: first-class
`exit_code`, base64 stdout stream, parsed command `chain`, timestamps,
and `process_id` linking start/update/completion.

### 2.4 Devin MCP (`mcp.devin.ai/mcp`)

`tools/list` succeeds **unauthenticated** (24 tools, full schemas —
**(live)**); `tools/call` requires `Bearer cog_*` — a **PAT on a Pro plan
works** (no enterprise tier needed, **live**). Evidence tools verified:

- `devin_session_interact` — `get` (session metadata incl.
  `acus_consumed`), `get_messages`, `get_attachments`, `archive`.
- `devin_session_events` — `list`/`details`/`search` (see §2.3).
- `devin_session_create` — creates sessions (consumes ACU; used once for
  the live probe).
- Non-evidence tools: knowledge/playbook/schedule/automation/review/
  code-scan/oncall/billing-tag/mcp-server/integration/user management,
  `devin_session_gather`, `devin_find_setting`.

### 2.5 DeepWiki MCP (`mcp.deepwiki.com/mcp`) — no session evidence

3 tools, fully callable unauthenticated **(live)**: `read_wiki_structure`,
`read_wiki_contents`, `ask_wiki_question`. Repo documentation only; nothing
about sessions, messages, or tool calls. (Doc drift: docs.devin.ai still
says `ask_question`/`list_available_repos`; live names are
`ask_wiki_question`/`list_wiki_repos`/`generate_wiki`.)

## 3. Equivalence matrix

Columns: **L** = local `sessions.db` · **A** = API v3 REST · **M** = Devin
MCP. `✓` exposed · `~` partial/degraded · `?` unverified · `—` absent.
Marks after values: nothing = verified live; `?` = still unverified.

| evidence | L | A | M | notes |
|---|---|---|---|---|
| session id | ✓ | ✓ | ✓ | |
| message stream | ✓ structured JSON | ~ flat text | ~ flat text | API/MCP `message` is a string; local `chat_message` carries role/blocks/tool_refs/thinking |
| tool invocation | ✓ | — REST | ✓ `shell_process_started.command` | verified live via MCP |
| tool name/kind | ✓ `kind` + `inferenceToolName` | — | ✓ `event_type`/`category` + `chain[].operation.kind` | needs an `event_type→kind` map; MCP is arguably richer (`operation.kind`=read/edit/…) |
| arguments | ✓ `rawInput` dict | — | ✓ `command` (+`chain[]`) | for shell; file/mcp/git shapes still `?` |
| result/output | ✓ `content[]` + `role=tool` | — | ~ `output_trunc` + base64 `terminal_update` stream | verified; output is truncated per field (`max_content_length`), full stream needs stitching `terminal_update` chunks |
| exit code | ✓ `terminal_exit.exit_code` | — | ✓ `shell_process_completed.exit_code` | verified live; note **string** type |
| per-event timestamps | — | ✓ | ✓ `created_at` + inner `timestamp` | **API/MCP strictly richer** |
| event ordering | ~ node tree only | ✓ chronological | ✓ | `tool_call_state` has no ordering column |
| session final state | ✓ sessions row | ✓ `status`+`status_detail` | ✓ `get` | richer upstream (quota/block reasons) |
| cost/ACU | — | ✓ `acus_consumed`, daily consumption | ✓ `acu_consumption_*` events | **API/MCP strictly richer** |
| tokens | ~ `num_tokens_preceding` | — | ~ `context_growth_update.tool_aggregates[].approx_ant_tokens`, `current_context_tokens` | MCP richer than REST here |
| thinking | ✓ `chat_message.thinking` | — | ✓ `devin_thoughts` + `one_line_thoughts` | verified live |
| subagent linkage | ~ `subagent_heads` (empty in practice) | ✓ `child_session_ids`/`parent_session_id` | ✓ `parent_session_id` filter | API richer |
| intent prompt | ✓ user-role messages | ✓ `source=user` | ✓ `initial_user_message` | |
| files touched | ✓ `locations[]` + mined | — | ~ `chain[].operation.paths`; `file`-category events `?` | partial — verified only via shell chain parsing |
| attachments | — | ✓ | ✓ `get_attachments` | |
| PR linkage | — | ✓ `pull_requests[]` | ✓ | |
| derived insights | — | ✓ (AI-generated) | — | second-order; not ground truth |
| integrity signal | ✓ NULL payloads, `raw_call_count` | ? `truncated_fields` | ~ pagination `has_next_page` + `truncated_fields` | arguably cleaner than local NULL-payload |
| working dir anchor for disk fallback | ✓ `sessions.working_directory` | — | ~ `starting_dir` exists but points at the **cloud VM**, not local disk | disk/git fallback predicates lose their anchor |

**Reading:** the equivalence is **asymmetric, not nested** — each side
carries evidence the other lacks. But for the claims qa-pack actually
verifies (`tests`, `push`, `commit`, `file`, `http`), the MCP events
stream supplies the same core fields as `tool_call_state`: command,
completion status, exit code, output — plus timestamps the local store
lacks.

## 4. Evidence levels for qa-pack

| level | definition | surface achieving it |
|---|---|---|
| **FULL** | `kind` + `commands` + `status` (exit-code-beats-status) + output strings + integrity signal → all action claims verifiable | local `sessions.db`; **Devin MCP `devin_session_events`** for `shell` claims (verified live); `file`/`mcp`/`git` shapes still `?` but same pattern |
| **PARTIAL** | invocation + completion known, output/exit missing → `tests`/`push`/`commit` verifiable as "ran", `http`/in-output claims → `unverifiable` | MCP events if a session's `contents` proves thin per type |
| **INSUFFICIENT** | session metadata + flat narrative only → no tool-call claims | REST-only view (`messages` endpoint); DeepWiki MCP |

`UNVERIFIED` keeps meaning "the record doesn't settle it", never "the
claim is false". PARTIAL evidence degrades verdicts, never fabricates
them (the aider-adapter contract).

## 5. Adapter contract (revised — now actionable)

An `mcp` source produces `SourceSession` from `devin_session_events`:

- `list` → per event, `event_type→kind` map: `shell_process_*→execute`,
  `file_*→read/edit` etc.; `direction==outgoing` keeps agent-side events
- `shell_process_started.contents.command` → `commands` (plus `chain[]`
  for sub-command semantics — a *richer* signal than rawInput)
- `shell_process_completed.contents.exit_code` → `status` (string→int;
  same exit-beats-status rule)
- `terminal_update.contents` (base64) + `output_trunc` → `search_text`,
  `http_statuses`
- `has_next_page` walk → completeness signal (`raw_call_count` analog);
  `truncated_fields` → mark degraded, not absent
- `devin_message` (outgoing) → claim extraction source;
  `initial_user_message` → intent
- `starting_dir`/`sessions.working_directory`: cloud VM path — the
  disk/git fallback predicates have **no anchor** on MCP-sourced
  sessions; FILE/COMMIT claims must rely on events only
- cost: `acus_consumed`/`acu_consumption_*` events — available upstream,
  absent locally (M2's cost item is satisfiable from this source)

The REST path adds nothing for verification (narrative only) — an `api`
source would be strictly weaker than `mcp`, useful only for metadata
enrichment (status_detail, consumption, PR linkage).

## 6. Open questions (smaller now)

1. `file`-/`mcp`-/`git`-category `contents` shapes — expected same typed
   pattern; one live session with file edits would confirm.
2. Whether `output_trunc` truncation is recoverable by walking
   `terminal_update` chunks (probably yes — they're the raw stream).
3. Why the SDK `events` REST endpoints 404 — unshipped, gated, or
   MCP-only by design? If they ship, an `api` source becomes equal to
   `mcp` minus the MCP dependency.
4. Secret-redaction behavior inside `contents` on sessions that actually
   use secrets (docs promise redaction; untested).
5. Rate limits on `devin_session_events` for large sessions (100s of
   events → paging cost).

## 7. Known gaps (explicit)

- `file`, `browser`, `mcp`, `git`, `secret`, `recording` `contents`
  shapes unverified — the live probe exercised `shell` only.
- The ~90 event types are not enumerated anywhere public; only the
  ~20 observed in two live sessions are confirmed by name.
- No enterprise `events` surface observed (SDK exposes org scope only).
- Local findings are schema-v17/Linux; Windows-era schemas and the
  `acp-messages/*.db` GUI store are documented in SCHEMA.md, not
  re-derived here.
- `mcp.devin.ai` discloses the full tool catalog unauthenticated —
  enumeration is public evidence, execution is gated (correctly).
- The live probe created and archived one trivial session (tag:
  `evidence-study`) — traceability of how §2.3/§3 were verified.
