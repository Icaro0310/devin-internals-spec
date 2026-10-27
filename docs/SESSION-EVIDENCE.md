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

Marks: **(verified)** = observed in a real store — a qualifier names the
verifier where it matters (`(verified, census)` = the real-store census;
`(verified, qa-pack)` = the qa-pack evidence provider, devin-assure #74) ·
**(unstable)** = format opaque/unverified — treat as opaque.

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
| `update_payload` | dict \| null | decoded result/update-side JSON object — or the inline result fields when the surface records no separate update (§4); `null` when absent, interrupted, or undecodable |
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

1. Read `kind`, then `type`, then `tool` — first present string wins,
   matched case-insensitively. A **specific known kind** decides
   immediately:
   - `_EXECUTE_KINDS = {execute, run, terminal, shell, bash, exec, command}`
     → `execute`
   - `_WRITE_KINDS = {edit, write, create, delete, move, rename}` → `write`
   - any other string is a **generic record name** (`function_call`,
     `custom_tool_call`, `tool_call`, `toolInvocation`, `toolInvocation*`,
     …) — it names the envelope, not the operation, so it does **not**
     decide; continue to step 2.
2. **Command sniff** — `command` or `cmd` carrying either a non-empty
   string or a **list-of-strings argv vector**, top-level or nested one
   level inside a dict-valued carrier under `rawInput`, `raw_input`,
   `input`, `args`, `arguments`, `parameters`, `action` (surface
   sections may name further carriers — §6.4 names `action.command`,
   §6.5 names `toolSpecificData.commandLine.original`) → `execute`. An
   argv list joins into a single space-separated command string for
   audit purposes — commands are compared as text downstream, never
   element-wise.
3. A `title` containing an `_EXECUTE_KINDS` token → `execute`.
4. Otherwise: the generic kind string from step 1, when one existed →
   `other`; none → `unknown`.

Only the specific known kinds outrank the command sniff — a `write`-kind
call carrying a cleanup command stays `write`; a `function_call` carrying
`pytest -q` is `execute`, never `other`.

Call/result **pairing**: surfaces that emit separate invocation and update
records pair them into one `EvidenceToolCall` — the invocation record
becomes `payload`, the update record `update_payload`. Pair keys, in
preference order: `toolCallId`, `tool_call_id`, `callId`, `call_id`, `id`.
An update record with no invocation emits a call whose `payload` is null
(interrupted calls are evidence too). **Surfaces whose invocation record
carries the result inline** populate `update_payload` from those inline
result/outcome fields — a missing second record is not missing result
evidence (§6.5 `toolInvocation.resultDetails`). `status`/exit codes are
*not* part of this model — the auditor derives them from
`update_payload`; the observed convention is exit-beats-status
(`_meta.terminal_exit` / `_meta["cognition.ai/terminal_exit"]` `exit_code`
outranks a `completed` status string, verified live on devin-cli).

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

### 6.1 `devin-cli` — `cli/sessions.db` **(verified v17 + live; qa-pack provider)**

*Verification status: layout verified live against schema-v17 stores via
`devin_internals` `SessionsStore`; the content mapping was re-verified by
the qa-pack provider (devin-assure #74).*

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
  (verified gap — `ts_ms` is always null; re-confirmed by the qa-pack
  provider).
- `working_dir` = `sessions.working_directory` verbatim.

### 6.2 `devin-chat` — `User/acp-messages/<session-uuid>.db` **(verified shape + versioned payload shapes)**

*Verification status: table shape verified across 2 real DBs by the
`devin_internals` ACP parser (SURFACES §6.2); payload shapes verified by
the 2026-10-27 census of 36 live stores → `fixtures/message-schemas/`
(`SCHEMA.md` §2). No qa-pack provider or agent-sessions source implements
this surface yet.*

- `messages` ordered by `position`. `kind` vocabulary verified by census:
  `user_message`, `agent_message`, `agent_thought`, `tool_call` under both
  `meta.schema_version` 1 and 6; v6 adds `plan` and `subagent`. The ACP
  session-update kind `tool_call_update` is documented here but was never
  observed — its fixtures are `unverified` until real data lands.
- `user_message` → `user`; `agent_message` and `agent_thought` →
  `assistant` (thinking text is agent-side content); `tool_call` →
  `EvidenceToolCall` (`payload` = decoded `payload` dict); a
  `tool_call_update` kind → `update_payload`, paired per §4 by the id
  inside the decoded payload. Unknown kinds are skipped + `partial-parse`,
  never fatal.
- No timestamp column — `ts_ms` null; ordering is `position`.

### 6.3 `copilot-cli` — `session-state` `events.jsonl` **(verified — census + qa-pack provider)**

*Verification status: envelope shape, `*.message`/`tool.*` type names and
the `data.toolCallId` pairing key are census-verified (191-event
real-store census — 16 `tool.execution_start` + 16
`tool.execution_complete`); the `data`-level keys below were verified by
the qa-pack provider (devin-assure #74). Deeper per-tool payload shapes
remain assumed.*

- Every event is an envelope `{id, parentId, timestamp, type, data}`
  **(verified, census)** — the envelope `id` is per-event and **never**
  pairs tool calls.
- `*.message` events → messages: `user.message` → `user`,
  `assistant.message` → `assistant`, `system.message` → `system`. Text
  from `data.content`/`text`/`message`/`reasoningText` **(verified,
  qa-pack)** — tolerant order; thinking text is agent-side content.
  `ts_ms` = the envelope `timestamp` (ISO) converted to epoch-ms.
- `tool.execution_start` / `tool.execution_complete` → `payload` /
  `update_payload`, paired strictly by `data.toolCallId` — the field the
  census-verified pair shares. Completion records carry `data.success`
  (bool) **(verified, qa-pack)** — normalize it to a status so exit
  state resolves (a real `status` field wins when present). When
  `toolCallId` is absent the fallback is **sequential pairing within the
  session** — a `complete` binds the most recent unpaired `start` —
  counted as one `partial-parse`.
- `working_dir` = the `workspace.yaml` seed beside `events.jsonl` —
  `git_root`, else `cwd` **(verified, qa-pack)**.
- **What remains assumed**: the census confirmed *type names* only, and
  qa-pack verified `toolCallId`/`success`/message-text keys — deeper
  per-tool `data` shapes were never enumerated. Command/status
  extraction is therefore the §4 tolerant rule only: `command`/`cmd`
  keys (possibly under `input`/`arguments`) → `execute`;
  `exitCode`/`status`/`output` keys in `complete` carry the result.
  Extractors must not hard-code deeper structure.
- `session.*`, `hook.*`, `permission.*`, `subagent.*`, `assistant.turn_*`
  events drive metadata, not evidence rows.

### 6.4 `codex-cli` — `state_<N>.sqlite` + `sessions/rollout-*.jsonl` **(verified — qa-pack provider)**

*Verification status: rollout record shapes, `session_meta` keys, exec
output nesting and the `threads` row fields below were verified by the
qa-pack provider (devin-assure #74); the agent-sessions TS parser
independently verifies the metadata leg (SURFACES §6.4). Inner key
spellings beyond the observed vocabulary remain partially verified → the
§4 tolerant rule is the contract, not a fallback.*

- `threads` rows and rollout files are **complementary legs of the same
  session — merged by session id, never a precedence fight**: the
  `threads` row supplies metadata (`native_id`, `cwd`,
  `created_at`/`updated_at`), the rollout JSONL supplies the evidence
  (`messages`, `tool_calls`). The §6.4 `duplicates` skip is a
  session-*listing* rule; it does not suppress evidence — a rollout whose
  `session_meta.id` equals a thread id merges into that thread's
  `SessionEvidence`. The link is `threads.rollout_path` where the column
  carries it (observed on some installs, unverified on this corpus),
  else scanning `sessions/`/`archived_sessions/` for the matching
  `session_meta.id`. Two readable files sharing an id still collapse —
  first readable copy supplies the evidence.
- Newest `state_<N>.sqlite` `threads` rows carry `cwd` and
  `first_user_message` but **no transcript** (verified, qa-pack) —
  `first_user_message` is the only row field that is honestly
  user-authored (`title`/`preview`/`summary` are auto-derived) and is
  emitted as a `user` message. A thread with **no locatable rollout**
  emits otherwise-empty `messages`/`tool_calls` plus `partial-parse`
  ("metadata-only session — no rollout file found"): the row proves the
  session existed, it does not prove nothing happened.
- Rollout records: `{timestamp, type, payload}` envelope with `type` ∈
  `response_item` | `event_msg` | `session_meta` **(verified, qa-pack)**
  (`ordinal` seen in the wild — extra keys ignored):
  - `session_meta` carries `id`, `cwd`, `git.root` and, on forks,
    `forked_from_id` **(verified, qa-pack)** — the metadata leg, never
    an evidence row itself. Forks are ignored entirely — a
    `forked_from_id` record never merges into the parent session.
  - `response_item`/`event_msg` payloads of `type: message` →
    `EvidenceMessage`: `role` verbatim-normalized (§3); text from
    `content[]` blocks (`input_text`/`output_text`-style `text`
    entries).
  - Tool calls pair an invoke record with an output record by `call_id`.
    Observed `payload.type` vocabulary **(verified, qa-pack)**: invoke
    side — `local_shell_call`, `exec_command_begin`, shell-named
    `function_call` (e.g. `name: "shell"`); result side —
    `local_shell_call_output`, `function_call_output`. Other names exist
    in the wild (`custom_tool_call`, `exec_command_end`, …) → the §4
    tolerant rule covers them.
  - Exec invocation `command` — top level or nested one level under a
    dict carrier such as `action` (a §4-named carrier —
    `action.command: ["pytest", "-q"]` → `execute`) — is an **argv
    list**: join elements on spaces into the single command string the
    §4 sniff audits (verified, qa-pack).
  - Exec outputs: the record's `output` field is a **JSON string or an
    already-decoded dict** — decode the string to the real dict;
    `metadata.exit_code` nests inside that document and a direct
    `exit_code` key is read as well (verified, qa-pack). An `exitCode`
    alias on the record normalizes to `exit_code`.
  - **Status convention for plain-text outputs (verified, qa-pack)**:
    Codex appends the status as the output's **last** line —
    `stdout…\nExit code: 0`. Only a full `Exit code: N` match on that
    last line is a status: an `Exit code:` substring mid-output stays
    stdout, and a **bare-integer output is stdout, never a status** — a
    failed run printing `0` must not read as exit 0.
  - `event_msg` task markers (`task_started`, `task_complete`,
    `token_count`, …), `turn_context`, `reasoning`, `compaction` → not
    evidence rows (task markers drive SURFACES §6.4 metadata).

### 6.5 `vscode-chat` — `chatSessions/*.json{,l}` **(verified — qa-pack provider + agent-sessions; part shapes unstable)**

*Verification status: mutation-log kinds/replay, workspace-folder
resolution and the terminal `exitCode` nesting below were verified by the
qa-pack provider (devin-assure #74); the mutation kinds were first
verified by the agent-sessions TS parser (SURFACES §6.5). Response-part
shapes still vary by VS Code version → tolerant extraction is the
contract.*

- `*.jsonl` chat files are **mutation logs, not snapshots** — replayed
  in order to reconstruct the document (verified): record kind `0`
  replaces the whole snapshot with `v`, `1` sets `v` at path `k`, `2`
  **truncates the array at path `k` to index `i` first** (when `i` is
  present) then appends items `v` — entries superseded by the
  truncation are not evidence — `3` deletes path `k` (`k` is a key
  path, `v` the value). For one session id the `.jsonl` **wins over a
  same-id `.json` snapshot**; unknown kinds are counted and skipped; a
  truncated tail is tolerated (`truncated-tail`). See SESSION-SURFACES
  §6.5.
- `working_dir` resolution (verified, qa-pack): the sibling
  `workspaceStorage/<wsDir>/workspace.json` `folder` field is a
  `file://` URI — URL-decode the path; `file:///C:/x` URIs strip the
  leading slash, a URI artifact ahead of a Windows drive letter, not
  part of the OS path. Failing that, the URL-decoded `<wsDir>` name
  counts **only when it still looks like a path** — a hashed `<wsDir>`
  id with no resolvable `workspace.json` folder yields **no
  `working_dir`, never fabricated** (+ warning).
- Each `requests[]` entry is a `user` message: text from `message.text` /
  `message` / `text` (tolerant), `ts_ms` from `timestamp`. A request is a
  user turn even when no text field survives.
- `request.response` parts: markdown/text-bearing parts concatenate into
  `assistant` messages (`ts_ms` from `responseTimestamp`); a part whose
  `kind` names a tool invocation (`toolInvocation` observed; tolerate any
  part carrying `toolCallId`/`toolId`) → `EvidenceToolCall`. The part is
  the **whole record — invocation and result live inline**:
  `toolSpecificData` (`kind == "terminal"` → `commandLine.original`
  counts as §4 `command` presence → `execute`) is the invocation side
  and stays the raw `payload`; the inline outcome fields — exit status
  at `toolSpecificData.terminalCommandState.exitCode` (verified,
  qa-pack), `resultDetails`, `isComplete` — populate `update_payload`
  per §4. `update_payload` is the **canonical home of extracted exit
  status** — auditors read it there even though no separate update
  record exists; `payload` never substitutes for it. Exact part shapes
  vary by VS Code version → tolerant extraction is the contract.
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
