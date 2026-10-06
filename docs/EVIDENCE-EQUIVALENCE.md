# EVIDENCE-EQUIVALENCE.md — local store vs official surfaces

Study of whether the evidence a verifier can extract from the local Devin
stores (`sessions.db` + siblings) is semantically reproducible from the
official surfaces (REST API v3, Devin MCP, DeepWiki MCP). Feeds the future
`devin-qa-pack --source local|api|mcp` adapter decision.

**Date:** 2026-10-06. **Method:** no credentials used. Local findings verified
against the live store (`~/.local/share/devin/cli/sessions.db`, schema v17)
and `SESSIONS_DB_DDL_V17`; API findings verified against the published
OpenAPI specs (`docs.devin.ai/{v1,v2,v3}-openapi.yaml`) and the `devinai`
PyPI wheel (0.1.0, Stainless-generated); MCP findings verified by live
unauthenticated `initialize`/`tools/list` against `mcp.devin.ai/mcp` and
`mcp.deepwiki.com/mcp` (server v2.14.3).

Marks: **(spec)** = in the published OpenAPI document · **(live)** = verified
against a running endpoint unauthenticated · **(sdk)** = present in the
`devinai` wheel but absent from the published spec · **(no-cred)** = the
surface documents/exposes it but payload fidelity needs a `cog_` key.

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
**(spec)**.

`GET .../sessions/{id}/messages` → `SessionMessage{event_id,
source(devin|user), message(string), created_at, origin, user_id, username}`
**(spec)** — flat narrative text; no structured tool payloads.

`GET .../sessions/{id}/insights` → AI-generated `analysis{timeline[],
issues[], classification, skill_usage, note_usage}` **(spec)** — derived
second-order evidence, not raw records.

`GET .../consumption/daily/sessions/{id}` → per-session ACU by date
**(spec)** — a field the local store lacks entirely.

### 2.3 The events surface — undocumented, closest analog

Not in the published spec, but real: the `devinai` SDK implements
**(sdk, no-cred)**:

| endpoint | response |
|---|---|
| `GET /v3/organizations/{o}/sessions/{d}/events` | `{event_id, event_type, category, direction, created_at, summary}[]`, cursor-paginated |
| `GET .../events/details` | same + `contents: Dict[str,object]` + `truncated_fields[]`; `max_content_length` default 10000; **secret values redacted** |
| `GET .../events/search` | same + `match_context`; case-insensitive over commands, file paths, messages, tool names, URLs |

~90 `event_type`s grouped into `category` ∈ {`shell`, `file`, `search`,
`browser`, `mcp`, `git`, `message`, `status`, `secret`, `todo`,
`recording`, `knowledge`, `playbook`, `webhook`, `lifecycle`, `other`};
`direction` ∈ {`incoming`, `outgoing`}. Example cited: `shell_process_started`.

### 2.4 Devin MCP (`mcp.devin.ai/mcp`) — same surface, tool-wrapped

`tools/list` succeeds **unauthenticated** (24 tools, full schemas —
**(live)**); `tools/call` requires `Bearer cog_*` **(live)**. Evidence tools:

- `devin_session_interact` — `get` (session metadata incl. `acus_consumed`),
  `get_messages` (source, created_at, event_id, body), `get_attachments`.
- `devin_session_events` — `list` / `details` / `search`, same params and
  categories as §2.3. This is the MCP projection of the events surface.
- Non-evidence tools: knowledge/playbook/schedule/automation/review/
  code-scan/oncall/billing-tag/mcp-server/integration/user management,
  `devin_session_gather` (status wait), `devin_find_setting` (deep links).

### 2.5 DeepWiki MCP (`mcp.deepwiki.com/mcp`) — no session evidence

3 tools, fully callable unauthenticated **(live)**: `read_wiki_structure`,
`read_wiki_contents`, `ask_wiki_question`. Repo documentation only; nothing
about sessions, messages, or tool calls. (Doc drift: docs.devin.ai still
says `ask_question`/`list_available_repos`; live names are
`ask_wiki_question`/`list_wiki_repos`/`generate_wiki`.)

## 3. Equivalence matrix

Columns: **L** = local `sessions.db` · **A** = API v3 · **M** = Devin MCP.
`✓` exposed · `~` partially / degraded · `?` unverifiable without credential
· `—` not exposed.

| evidence | L | A | M | notes |
|---|---|---|---|---|
| session id | ✓ | ✓ | ✓ | `sessions.id` ↔ `session_id` ↔ `devin_session_*` |
| message stream | ✓ structured JSON | ~ flat text | ~ flat text | API/MCP `message` is a string; local `chat_message` carries role/blocks/tool_refs/thinking |
| tool invocation | ✓ | ~ `events` list | ~ `devin_session_events` list | event `summary`/`event_type`, not the invocation payload |
| tool name/kind | ✓ `kind` + `inferenceToolName` | ~ `event_type`/`category` | ~ same | naming granularity differs (`execute`/`exec` vs `shell_process_started`) — needs a type map |
| arguments (`rawInput`) | ✓ | ? inside `contents` | ? same | **(no-cred)** — contents shape is per-type, untyped |
| result/output | ✓ `content[]` + `role=tool` | ? inside `contents`, truncatable | ? same | truncation at 10k chars default; secrets redacted |
| exit code | ✓ `terminal_exit.exit_code` | ? inside `contents` for shell events | ? same | the critical field; a `shell_process_*` pair suggests lifecycle events carry it — unverified |
| per-event timestamps | — | ✓ `created_at` | ✓ | **API/MCP strictly richer** than local |
| event ordering | ~ node tree only | ✓ chronological | ✓ | `tool_call_state` has no ordering column |
| session final state | ✓ sessions row | ✓ `status`+`status_detail` | ✓ `get` | richer upstream (`waiting_for_approval`, quota reasons) |
| cost/ACU | — | ✓ `acus_consumed`, daily consumption | ✓ | **API/MCP strictly richer** |
| tokens | ~ `num_tokens_preceding` | — | — | local-only signal |
| subagent linkage | ~ `subagent_heads` (empty in practice) | ✓ `child_session_ids`/`parent_session_id` | ✓ `parent_session_id` filter | API richer |
| intent prompt | ✓ user-role messages | ✓ `source=user` messages | ✓ | |
| files touched | ✓ `locations[]` + mined | ? inside `file`-category `contents` | ? | |
| attachments | — | ✓ | ✓ | API/MCP only |
| PR linkage | — | ✓ `pull_requests[]` | ✓ | API/MCP only |
| derived insights | — | ✓ (AI-generated) | — | second-order; not ground truth |
| row-level integrity signal | ✓ NULL payloads, `raw_call_count` | ? `truncated_fields` | ? | local interruption marker has no known analog |

**Reading:** the equivalence is **asymmetric, not nested**. Neither surface
is a subset of the other — each carries evidence the other lacks
(timestamps/ACU/attachments/PRs upstream; rawInput fidelity/exit-code-vs-
status semantics/token counts locally). "Not equivalent" would not be a
failure of the surfaces; it is the architecture of them.

## 4. Evidence levels for qa-pack

Map each surface to the maximum predicate fidelity it can feed a
`ParsedToolCall` stream:

| level | definition | surface example |
|---|---|---|
| **FULL** | `kind` + `commands` + `status` incl. exit-code-beats-status + output strings + integrity signal — all six claim kinds verifiable | local `sessions.db` today |
| **PARTIAL** | invocation + completion known, output/exit-code missing or untrusted — `tests`/`push`/`commit` verifiable as "ran"; `http`/`file`-in-output claims degrade to `unverifiable` | API/MCP events if `contents` lacks exit_code/output; precedent: `aider` adapter emits `status="unknown"` |
| **INSUFFICIENT** | session metadata + narrative only — no tool-call claims verifiable | published-spec-only view (messages endpoint), DeepWiki MCP |

This preserves the core semantic: `UNVERIFIED` means "the record doesn't
settle it", never "the claim is false" — and PARTIAL evidence must degrade
verdicts, not fabricate them (the aider-adapter contract).

## 5. Adapter contract (when the time comes)

A future `api`/`mcp` source only needs to produce `SourceSession`:

- `events` list → `ParsedToolCall.kind` via an `event_type→kind` map
  (`shell_*→execute`, `file_*→read/edit`, `mcp_*→execute`-ish; the
  `inferenceToolName` analog is unknown) **(no-cred)**
- `events/details` `contents` → `commands` (command dig), `search_text`
  (all strings), `http_statuses`, exit code — **if** contents carries them
- `total`/pagination completeness → `raw_call_count` analog (did we see
  every event? `has_next_page` gives this cleanly — arguably *better* than
  the local NULL-payload signal)
- `messages` (source=user first) → intent; `source=devin` → claims
- `SessionResponse.working_directory`-equivalent: **absent** — no cwd field
  exists in `SessionResponse`; the disk/git fallback predicates
  (`git cat-file`, `exists()`) have no anchor on API-sourced sessions.

## 6. Open questions (credential-gated)

1. Does event `contents` carry command strings, exit codes, and output text
   per event_type? (decides FULL vs PARTIAL for the whole API/MCP path)
2. What is the `event_type` → local `kind`/`inferenceToolName` mapping?
3. Is `direction` sufficient to separate agent-initiated calls from
   user/system events (needed to keep claim extraction on agent output)?
4. Does `events/details` honor `truncated_fields` enough to serve as the
   `raw_call_count` integrity signal?
5. MCP and REST `events` — same backend, same fidelity?

## 7. Known gaps (explicit)

- Everything marked **(no-cred)** is inferred from SDK types and live
  schema enumeration; no `tools/call` or authenticated GET was possible.
- The ~90 event types are not enumerated anywhere public; only
  `shell_process_started` is cited in SDK docstrings.
- The enterprise `events` surface may not exist (SDK exposes it
  org-scoped only).
- Local findings are schema-v17/Linux; Windows-era schema versions and the
  `acp-messages/*.db` GUI store are documented in SCHEMA.md but were not
  re-derived here.
- `mcp.devin.ai` discloses the full tool catalog unauthenticated —
  enumeration is public evidence, execution is gated.
