# SPEC 01 — `devin-internals-spec` (Slot 0)

## 1. Problem

Nobody can build reliable Devin tooling because the format of the local data
is not public and it **changes**: `sessions.db` has already had **17 migrations**
(v1–v15 on 2026-05-06, v16 on 2026-07-05, v17 on 2026-09-14). Existing
documentation (tokmesh, UniSessions) covers **only the CLI** — the **Devin
Desktop** store (`acp-messages/*.db`, `state.vscdb`, locks,
`refinery_schema_history`) is not documented anywhere.

Evidence: today's audit had to discover the schema by reverse engineering,
and existing tools break silently when the schema changes.

## 2. Devin extra (and the 3 tests)

**Extra:** it is the **only map of the Devin Desktop/GUI store**, and it ships a
**version detector** that makes any tool fail with a clear message instead of
corrupting data.

- **Side-by-side competitor:** tokmesh/UniSessions document the CLI; they do
  **not** cover `acp-messages`, `state.vscdb` (`windsurfSpace.*`), orphan locks
  or `refinery_schema_history`. Ours does something they cannot.
- **No-Devin:** if Devin is removed, there is no store to document — the extra
  disappears.
- **One sentence:** *"It's the map of what Devin keeps on your disk — and it
  warns you when that changes."*

## 3. Scope

- Spec of the **3 stores**: `sessions.db`, `acp-messages/*.db`, `state.vscdb`.
- ER diagram + field-by-field description of the relevant tables
  (`sessions`, `message_nodes`, `tool_call_state`, `refinery_schema_history`,
  GUI `meta`/`messages`, `windsurfSpace.*` keys).
- **Version detector**: reads `refinery_schema_history` +
  `app_state.schema_compat_version`; fails loudly on an unknown version.
- **Fixture generator**: creates minimal valid synthetic DBs (v15/v16/v17),
  plus minimal `acp-messages` and `state.vscdb`.
- **`devin-inspect` CLI**: `schema`, `sessions`, `health` (read-only).

## 4. Non-scope

- Does not analyze or export session content (that is `devin-history`).
- Does not write to the DB (read-only, always).
- Does not document the plugins/skills format (that belongs to Cognition,
  already published).
- Not an MCP in v1 (read-only MCP comes later, if requested).

## 5. Interfaces

| Interface | Description |
|---|---|
| **Library** `devin_internals` | Parsing + version detection (source of truth for other repos) |
| **CLI** `devin-inspect` | `schema` · `sessions` · `health` |
| **Docs** | `SPEC.md` (the public document) + `SCHEMA.md` |
| **PyPI** | `pipx install devin-internals-spec` |

## 6. Output format / data contract

- `SPEC.md`: versioned document (`spec v0.1`) — open to RFC.
- Detector returns `{"schema_version": 17, "known": true, "min_supported": 15}`.
- Fixtures: generated `.db` files, deterministic (fixed seed), versioned in the
  repo.

## 7. Fixtures and tests (TDD — fixtures first)

1. Synthetic `sessions.db` generator (with the 17 migrations applied).
2. Per-version fixtures: v15, v16, v17 (to test compatibility).
3. Minimal `acp-messages` (meta + messages) and `state.vscdb` fixtures.
4. Tests: version detection · parsing of each table · **clear failure** on an
   unknown version · generator idempotency · Windows encoding/paths.
5. CI: Windows + Linux.

## 8. Risks and mitigation

| Risk | Mitigation |
|---|---|
| Schema changes | Version detector + per-version fixtures + local nightly CI |
| Documentation goes stale | Mark each field as "verified in vX"; spec changelog |
| Terms of use (reading local DB) | Check terms; read-only; zero network; document in SECURITY.md |
| Someone depends on an undocumented field | Publish only what is verified; mark the rest "unstable" |

## 9. Definition of done

- [ ] `SPEC.md` published with the 3 stores documented
- [ ] Detector fails loudly on an unknown version (dedicated test)
- [ ] Fixtures v15/v16/v17 generate valid DBs that open with the parser
- [ ] `devin-inspect health` runs on Windows and Linux
- [ ] Tests green on Windows + Linux · README (EN) with Prior art and
  Limitations
- [ ] `pipx install devin-internals-spec` works

## 10. Tasks (in order)

1. Fixture generator (v17) + open test.
2. `sessions.db` + `refinery_schema_history` parser → version detector.
3. v15/v16 fixtures + compatibility tests.
4. `acp-messages` and `state.vscdb` parser.
5. Write `SPEC.md`/`SCHEMA.md` (EN).
6. `devin-inspect` CLI.
7. Publish PyPI + repo + CI.
