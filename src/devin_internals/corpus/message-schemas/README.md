# `fixtures/message-schemas/` — versioned ACP payload shape corpus

Executable form of `docs/SCHEMA.md` §2. One JSON fixture per
(`messages.kind`, `meta.schema_version`) pair, plus one `_meta` fixture
per store version covering the `meta` table. Fixtures record **shape
only** — field names, JSON types, presence and closed discriminator
vocabularies — never message contents.

## Fixture format (`message-schema`, `format_version: 1`)

```json
{
  "fixture": "message-schema",
  "format_version": 1,
  "store": "User/acp-messages/<session-uuid>.db",
  "table": "messages" | "meta",
  "kind": "<messages.kind or '_meta'>",
  "meta_schema_version": 6,
  "status": "verified" | "unverified",
  "provenance": "<how the shape was derived>",
  "fields": { "<path>": <field spec>, ... },
  "store_checks": ["message_count_equals_row_count", ...],   // meta only
  "notes": ["..."]
}
```

### Field paths

- `a.b` — object child. `a[]` — each element of list `a` (the field
  behind `a[]` is the `a` spec itself, typed `list`).
- `["literal.key"]` — bracket form for names containing dots, e.g.
  `content[]._meta["cognition.ai/timestamp"]`.
- For `meta` fixtures the root object is the `meta` table's `key`/`value`
  map; `json_text: true` on a field means its string value decodes to a
  JSON object that the nested paths then apply to (`info.title`).

### Field spec keys

| key | required | meaning |
|---|---|---|
| `types` | yes | JSON type names observed: `str` `int` `float` `bool` `null` `list` `dict` |
| `presence` | yes | `always` = present on every observed parent instance · `sometimes` = optional. **Asserted only for verified fields.** |
| `status` | yes | `verified` = observed in real captured stores · `unverified` = documented (spec prose or a sibling fixture) but never confirmed — **never asserted** |
| `open` | — | children of this node are an open key space — undeclared children are expected, never reported |
| `closed` | — | the `values` + `documented_unverified` union is the complete documented vocabulary — a value outside both is a contradiction. Only allowed on `verified` fields. |
| `json_text` | — | the field's string value is JSON-encoded; child paths apply to the decoded object |
| `values` | — | observed discriminator vocabulary (schema vocabulary only — never content values) |
| `documented_unverified` | — | documented vocabulary never observed; observing one is a promotion note |
| `note` | required on `unverified` | provenance/why the field is marked the way it is |

### Verification semantics (`devin_internals.message_schemas`)

- **Contradictions** (fail-loud): a verified `always` field missing · a
  verified field with a type outside `types` · a value outside a
  `closed` vocabulary · a `messages.kind` or `meta.schema_version` with
  no fixture · a `store_checks` invariant violated · a payload that is
  not a JSON object.
- **Promotions** (never fatal): an `unverified` field or a
  `documented_unverified` vocabulary value observed in real data —
  candidates for promotion to `verified` on the next evidence pass.
- **Notes** (never fatal): `new_vocabulary` (value outside the observed
  set of an open vocabulary) · `undeclared_fields` (keys no fixture
  documents, outside `open` nodes) · `extra_meta_keys` (the `meta` key
  space is open per spec).
- Unverified fields are **never** asserted — not presence, not type,
  not vocabulary — and a fixture cannot nest a `verified` field under
  an `unverified` parent (the loader rejects it).

### `store_checks` (meta fixtures, all verified invariants)

- `message_count_equals_row_count` — `meta.message_count` (TEXT integer)
  equals `COUNT(messages)`. Verified on all 36 sampled stores.
- `positions_contiguous_zero_based` — `messages.position` is a
  contiguous `0..n-1` sequence. Verified on all 36 sampled stores.

## Version coverage

`meta.schema_version` selects the fixture set: **v1** knows
`user_message`, `agent_message`, `agent_thought`, `tool_call`; **v6**
adds `plan` and `subagent`. `tool_call_update` fixtures exist for both
versions as `unverified` (documented in `docs/SESSION-EVIDENCE.md` §6.2,
absent from all sampled stores). A kind or version with no fixture is a
contradiction — the intended drift signal.

## Regenerating / updating fixtures

Fixtures are evidence-derived: fields marked `verified` must have been
observed in real captured stores; `unverified` marks what the spec or a
sibling fixture documents without real-data confirmation. To rescan a
store family, run

```
python -m devin_internals.message_schemas extract <db> [--kind K]
```

which prints the aggregated shape (paths, types, presence) — and

```
python -m devin_internals.message_schemas verify <db|dir>
```

which verifies store(s) against this corpus (exit 1 on contradictions).
When a real store contradicts a verified field, either the store is
drift (update the spec + fixture in the same PR, recording the new
evidence) or the fixture was wrong (demote it honestly — a wrong
`verified` mark is worse than an `unverified` gap).
