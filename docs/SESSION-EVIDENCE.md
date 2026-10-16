# SESSION-EVIDENCE.md — canonical spec for session evidence (content layer)

The contract for reading **any agent's** local session store into the shared
canonical *evidence* model: the messages an agent sent and the tool calls it
recorded. This is the content layer `SESSION-SURFACES.md` §8 deliberately
excludes — `SessionMeta` answers "which sessions exist, where, and when";
`SessionEvidence` answers "what did the agent say it did, and what do the
recorded tool calls show". The primary consumer is the claims-vs-evidence
auditor (**devin-assure** `qa-pack`): did the agent claim tests passed, and
did a tool call actually run the test suite successfully?

**Rule: implement from this document, never from the other implementation's
code.** When two implementations disagree, the bug is in whichever side
diverges from this text — and the text, once corrected, is updated in the
same PR as the fix (same posture as SESSION-SURFACES, D-2026-10-15).

Marks: **(verified)** = observed in a real store · **(unstable)** = format
opaque/unverified — treat as opaque.

---

## 1. Relationship to SESSION-SURFACES

- `surface` uses the **closed set** in SESSION-SURFACES §1 — never outside
  it. `native_id` is the store's own identifier, as there.
- `ref` binds evidence to metadata: the **canonical id** from
  SESSION-SURFACES §4 when one is derivable (native id + workspace
  identity), else the session's **ephemeral `display_key`** (§2). Evidence
  never invents its own identity — a session with `id: null` in the metadata
  layer keeps `unknown-workspace` and is keyed by `display_key`.
- `started_at` is the same ISO 8601 instant the metadata layer emits.
- `warnings` draws **only** from the SESSION-SURFACES warning vocabulary
  (§4/§5/§6). Evidence extraction adds no new codes: unreadable or
  unparsable content rows count toward `partial-parse`, a broken tail is
  `truncated-tail`, hidden sessions are skipped per §3.

## 2. Canonical model — what every extractor emits (normative)

One `SessionEvidence` per session:

| field | type | contract |
|---|---|---|
| `surface` | enum (SURFACES §1) | never outside the closed set |
| `native_id` | string | the store's own session id |
| `ref` | string | canonical id (§4) or ephemeral `display_key` — §1 |
| `started_at` | ISO 8601 \| null | same value as `SessionMeta.started_at` |
| `working_dir` | string \| null | the **real path** — never hashed. The workspace anchor disk/git fallback predicates need; §7 privacy contract governs it |
| `messages` | `EvidenceMessage[]` | store order; see §3 |
| `tool_calls` | `EvidenceToolCall[]` | store order where defined; see §4 |
| `warnings` | list | SESSION-SURFACES codes only — §1 |

`EvidenceMessage`:

| field | type | contract |
|---|---|---|
| `role` | enum | `user` \| `assistant` \| `tool` \| `system` — normalized per §3 |
| `text` | string | decoded message text; `""` when the record carries none |
| `ts_ms` | int \| null | epoch **milliseconds**; `null` when the store has no per-message time |

`EvidenceToolCall`:

| field | type | contract |
|---|---|---|
| `tool_call_id` | string | the store's call id; a deterministic synthetic id (e.g. `<surface>-call-<n>`) when the store pairs call/result positionally instead |
| `kind` | enum | `execute` \| `write` \| `other` \| `unknown` — normalized per §4 |
| `payload` | dict \| null | decoded invocation-side JSON object; `null` when absent *or* undecodable — an unparsable row still emits a call, never silently dropped |
| `update_payload` | dict \| null | decoded result/update-side JSON object; `null` when absent, interrupted, or undecodable |
| `ts_ms` | int \| null | epoch ms; `null` when the store records no per-call time (devin-cli §6.1) |

Extractors run against a store read by the SESSION-SURFACES §3 read
contract (read-only, `mode=ro` + `immutable=1` retry, hidden rows skipped).
The `raw row count` before decoding matters to the auditor — rows that
exist but fail to decode mean *unreadable* ground truth, not *absent*
ground truth; emitting them as `EvidenceToolCall` rows with null payloads
preserves that distinction end-to-end.

## 3. Role vocabulary — normalized closed set

| store role spelling | canonical role |
|---|---|
| `user`, `human` | `user` |
| `assistant`, `agent`, `agent_message` | `assistant` |
| `tool`, `tool_result`, `function`, `function_call_output` (as a message row) | `tool` |
| `system` | `system` |

Claim extraction consumes **agent-side** text only — `user`/`tool`/`system`
messages are context and evidence, never delivery claims. A message whose
role cannot be determined is **not** guessed: `devin-cli` message payloads
that fail to decode entirely are emitted with role `assistant` and counted
`partial-parse` (the `message_nodes` forest is the agent transcript — user
prompts primarily live in `prompt_history`, outside this spec's scope);
every other surface skips the undecodable record and counts `partial-parse`.

## 4. Tool-call kind normalization (normative)

Per `EvidenceToolCall`, inspect the decoded invocation `payload` (the
update side never decides `kind`):

1. Read `kind`, then `type`, then `tool` — first present string wins;
   match case-insensitively:
   - `_EXECUTE_KINDS = {execute, run, terminal, shell, bash, exec, command}`
     → `execute`
   - `_WRITE_KINDS = {edit, write, create, delete, move, rename}` → `write`
   - any other string → `other`
2. No kind/type/tool key: a `title` containing an `_EXECUTE_KINDS` token →
   `execute`.
3. Still nothing: **sniff** — `command` or `cmd` present as a non-empty
   string (top-level or nested under `rawInput`, `raw_input`, `input`,
   `args`, `arguments`, `parameters`) → `execute`.
4. Otherwise → `unknown`.

Call/result **pairing**: surfaces that emit separate invocation and update
records pair them into one `EvidenceToolCall` — the invocation record
becomes `payload`, the update record `update_payload`. Pair keys, in
preference order: `toolCallId`, `tool_call_id`, `callId`, `call_id`, `id`.
An update record with no invocation emits a call whose `payload` is null
(interrupted calls are evidence too). `status`/exit codes are *not* part of
this model — the auditor derives them from `update_payload`; the observed
convention is exit-beats-status (`_meta.terminal_exit` /
`_meta["cognition.ai/terminal_exit"]` `exit_code` outranks a `completed`
status string, verified live on devin-cli).

## 5. Ground-truth precedence (normative)

**Structured tool evidence outranks message text.** That is the audit's
point: a claim in an assistant message ("tests passed", "pushed to main")
is verified only by a corroborating `EvidenceToolCall` — never by the
message itself. When structured evidence and narrative disagree, the
structured record wins; when no structured record exists the claim is
*unverified-by-evidence*, not *false* — `unverified`/`no-evidence` mean
"the record doesn't settle it", never "the claim is a lie". `tool`-role
message text is ranked below the structured `update_payload` it duplicates.

## 6. Per-surface extraction mapping (normative)

### 6.1 `devin-cli` — `cli/sessions.db` **(verified v17 + live)**

- **messages**: `message_nodes.chat_message` decoded per row, ordered by
  `node_id`. The payload is **(unstable)** — decode defensively: `role`
  from `role`/`author`/`sender` (normalized §3), text from
  `text`/`content`/`message`/`body`/`markdown` (string, or content-block
  list of `{text}` joined on `\n`). `ts_ms` from `created_at` with the
  §6.1 magnitude rule (`< 1e12` → seconds × 1000). `role=tool` rows are
  emitted as `tool` messages — the result transcript, duplicating update
  payloads at lower precedence (§5). `prompt_history` is **not** evidence
  (recall buffer; see §9).
- **tool_calls**: one `EvidenceToolCall` per `tool_call_state` row —
  `tool_call_id` verbatim, `payload` = decoded `tool_call_json` (null on
  NULL or decode failure), `update_payload` = decoded
  `tool_call_update_json`. Observed payload fields **(verified live)**:
  invocation `kind`, `title`, `rawInput` dict, `locations[].path`; update
  `status`, `content[]` output text, `_meta.terminal_exit.{exit_code,
  signal}`, `cwd`. **No per-call timestamp or ordering column exists**
  (verified gap — `ts_ms` is always null).
- `working_dir` = `sessions.working_directory` verbatim.

### 6.2 `devin-chat` — `User/acp-messages/<session-uuid>.db` **(verified shape; kinds unstable)**

- `messages` ordered by `position`. `kind` vocabulary observed live:
  `user_message`, `agent_message`, `agent_thought`, `tool_call` — plus ACP
  session-update kinds `tool_call`/`tool_call_update`.
- `user_message` → `user`; `agent_message` and `agent_thought` →
  `assistant` (thinking text is agent-side content); `tool_call` →
  `EvidenceToolCall` (`payload` = decoded `payload` dict); a
  `tool_call_update` kind → `update_payload`, paired per §4 by the id
  inside the decoded payload. Unknown kinds are skipped + `partial-parse`,
  never fatal.
- No timestamp column — `ts_ms` null; ordering is `position`.

### 6.3 `copilot-cli` — `session-state` `events.jsonl` **(envelope + type names verified; data keys unverified)**

- `*.message` events → messages: `user.message` → `user`,
  `assistant.message` → `assistant`, `system.message` → `system`. Text from
  `data.text`/`content`/`message` (tolerant). `ts_ms` = the envelope
  `timestamp` (ISO) converted to epoch-ms.
- `tool.execution_start` / `tool.execution_complete` are **observed real
  event types** (16 of each in a 191-event real-store census). `start` →
  `payload`, `complete` → `update_payload`, paired per §4
  (`data.toolCallId`-style keys, else the event `id`).
- **What is unverified**: the discovery census confirmed *type names*
  only — `data` contents were never read. Extraction of commands/status is
  therefore the §4 tolerant rule only: `command`/`cmd` keys (possibly
  under `input`/`arguments`) → `execute`; `exitCode`/`status`/`output`
  keys in `complete` carry the result. Any other inner key layout is
  plausible — extractors must not hard-code deeper structure.
- `session.*`, `hook.*`, `permission.*`, `subagent.*`, `assistant.turn_*`
  events drive metadata, not evidence rows.

### 6.4 `codex-cli` — `state_<N>.sqlite` + `sessions/rollout-*.jsonl` **(spec v3.4.4)**

- `threads` rows carry **no content** — a thread-only session emits empty
  `messages`/`tool_calls` unless its rollout file is locatable (the
  `threads.rollout_path` link is observed on some installs, unverified on
  this corpus — treat as absent).
- Rollout records: `{timestamp, type, payload}` envelope (`ordinal` seen
  in the wild — extra keys ignored):
  - `response_item` payloads of `type: message` → `EvidenceMessage`:
    `role` verbatim-normalized (§3); text from `content[]` blocks
    (`input_text`/`output_text`-style `text` entries).
  - `type: function_call` / `custom_tool_call` → `EvidenceToolCall`
    `payload`; `function_call_output` → `update_payload`, paired by
    `call_id`. Exec records carry `command`+`output` keys — the §4 sniff
    classifies them `execute`; `exit_code`/`output` inside the output
    payload carry the result.
  - `session_meta`, `event_msg` (`task_started`, `task_complete`,
    `token_count`, …), `turn_context`, `reasoning`, `compaction` → not
    evidence rows (task markers drive SURFACES §6.4 metadata).
  - Forks are ignored and `duplicates` resolve per §6.4 — first readable
    copy wins; the skipped file contributes no evidence.
- Inner key spellings of exec payloads are only partially verified → the
  §4 tolerant rule is the contract, not a fallback.

### 6.5 `vscode-chat` — `chatSessions/*.json{,l}` **(spec v3.4.4; part shapes unstable)**

- Replay `.jsonl` mutation logs per SESSION-SURFACES §6.5 (kinds 0–3,
  `.jsonl` wins over `.json`, truncated tail tolerated) → final document,
  then extract.
- Each `requests[]` entry is a `user` message: text from `message.text` /
  `message` / `text` (tolerant), `ts_ms` from `timestamp`. A request is a
  user turn even when no text field survives.
- `request.response` parts: markdown/text-bearing parts concatenate into
  `assistant` messages (`ts_ms` from `responseTimestamp`); a part whose
  `kind` names a tool invocation (`toolInvocation` observed; tolerate any
  part carrying `toolCallId`/`toolId`) → `EvidenceToolCall`.
  Terminal-specific data (`toolSpecificData.kind == "terminal"`,
  `commandLine.original`, `resultDetails`) carries command + result —
  §4 sniff → `execute`. Exact part shapes vary by VS Code version →
  tolerant extraction is the contract.
- Out of scope today (observed on disk, not spec'd):
  `chatEditingSessions/<id>/state.json`,
  `GitHub.copilot-chat/transcripts|debug-logs`, `session-store.db`.

## 7. Privacy contract (normative)

- `working_dir`, message text, and both payload dicts are **LOCAL-ONLY
  evidence**: never exported, never sent over a network, never embedded
  verbatim in reports beyond the claim-relevant snippets the auditor
  already controls (the qa-pack precedent: ≤160-char excerpts).
- Readers are strictly read-only: SQLite opens `mode=ro` and retries
  `immutable=1` (closing the failed handle in between); files are read,
  never written.
- `SessionEvidence` objects are in-memory views; persisting them is out
  of scope. The metadata layer's `workspace_hash` rule still applies to
  anything that *leaves* the process — the real `working_dir` never
  crosses a boundary.

## 8. Evidence manifest — `fixtures/session-corpus/evidence-manifest.json`

Version 1. One flat entry per corpus session, sorted by
`(surface, native_id)`:

| field | contract |
|---|---|
| `surface` | the session's surface |
| `native_id` | same id `manifest.json` binds |
| `expected_claims[]` | `{kind, verdict}` — `kind ∈ {tests, commit, file, push, http, url}` (the qa-pack claim vocabulary); `verdict ∈ {verified, unverified, no-evidence}` |
| `expected_tool_call_kinds[]` | sorted unique §4 kinds an extractor must produce |
| `expected_message_roles[]` | sorted unique §3 roles present in the store |

Verdict semantics (manifest-side, not the auditor's status names):
`verified` — recorded tool evidence corroborates the claim (e.g. a
`pytest` call exiting 0) · `unverified` — tool evidence exists but does
not corroborate it (failed call, unrelated command, ambiguous state) ·
`no-evidence` — the claim text exists but no tool call is recorded.

**Every corpus session gets an entry.** Sessions whose store carries no
content layer (codex `threads` rows, task-marker-only rollouts) keep
minimal all-empty expectations — present and asserted, never omitted.
Entries are hand-derived from the fixtures, like `manifest.json`
`expect` blocks; `tests/test_session_corpus.py` re-derives them from the
generated bytes so drift fails loudly. And like `manifest.json`, nothing
content-shaped reaches the file — no claim text, no commands, no paths.

## 9. Explicit non-scope

- No verdict computation — claim detection and verdict naming belong to
  the auditor (`SourceSession`/`ParsedToolCall` in qa-pack are an
  *application* of this model, not part of it).
- No cross-store correlation (a `devin-cli` session and a `devin-chat`
  session are different sessions — same posture as SURFACES §8).
- `prompt_history`, `rendered_commits`, `subagent_heads`, intent
  reconstruction — adjacent tables, not evidence rows today.
- Remote evidence surfaces (REST `SessionMessage`, Devin MCP
  `devin_session_events`) — `docs/EVIDENCE-EQUIVALENCE.md` covers the
  equivalence study; the canonical remote contract is a separate spec.
- `state.vscdb`, `session_locks/`, WAL siblings — observed, not spec'd
  (SCHEMA.md §4).
