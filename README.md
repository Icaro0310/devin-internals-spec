# devin-internals-spec

> **Unofficial community project.** Not affiliated with, endorsed by, or
> sponsored by Cognition AI. "Devin" is a trademark of Cognition AI.

**[Português (BR)](README.pt-BR.md)** · English

A documented map of Devin's local session stores — the CLI `sessions.db`, the
Desktop GUI `acp-messages/*.db` and `state.vscdb` — plus a schema-version
detector and deterministic synthetic fixtures, so tooling fails loudly instead
of silently misreading your data.

## The problem

Everything Devin stores on your disk is kept in undocumented SQLite databases
whose schema **changes without notice**: `sessions.db` has already gone through
**17 migrations** (v1–v15 on 2026-05-06, v16 on 2026-07-05, v17 on 2026-09-14).
Any tool that reads these stores has to reverse-engineer the format — and when
Cognition ships the next migration, those tools break *silently*: wrong counts,
missed rows, or corrupted interpretation, with no error raised.

The Devin Desktop app is worse off than the CLI: its stores
(`acp-messages/*.db`, `state.vscdb`, session locks, the
`refinery_schema_history` migration ledger) are not documented anywhere.

## Prior art

Session-log tooling exists for other agent CLIs — e.g. **tokmesh** and
**UniSessions** document and parse Devin's CLI `sessions.db`. This project does
not reinvent that: it borrows the same idea (SQLite schema → typed parsing) and
extends it to what those tools don't cover — the Desktop GUI stores — and adds
the piece they lack: an explicit **schema-version gate** so a parser refuses to
run against a schema it has never seen.

## What makes it Devin-native

The differentiator, in one sentence: *it's the map of what Devin keeps on your
disk — and it warns you when that changes.*

1. **Side-by-side:** it covers `acp-messages/*.db`, `state.vscdb`
   (`windsurfSpace.*` keys) and `refinery_schema_history`, which no existing
   tool documents.
2. **No-Devin:** remove Devin and there is no store to document — the extra
   disappears entirely.
3. **Loud failure:** `detect_schema_version()` returns a version contract and
   raises on anything unknown, instead of guessing at bytes.

## Install

```bash
pipx install devin-internals-spec   # once published to PyPI
```

For development:

```bash
pip install -e ".[dev]"
pytest
```

## Usage

```bash
devin-internals-spec --help
```

As a library (this is the supported interface — the CLI is a thin wrapper):

```python
from devin_internals import detect_schema_version

detect_schema_version("~/AppData/Roaming/devin/cli/sessions.db")
# {"schema_version": 17, "known": True, "min_supported": 15, ...}
```

## Limitations

- **Private, volatile internals.** These stores are implementation details of
  Devin; the schema can change in any release. Only what is marked "verified"
  in `docs/SPEC.md` should be relied on.
- **Verified against schema v17** only (the latest at time of writing). The
  detector *refuses* versions it doesn't know — that's a feature, but it means
  new Devin releases will break detection until the spec is updated.
- **Read-only.** This project never writes to Devin's databases.
- **Not a session exporter.** It documents and guards the format; it does not
  dump your conversations (that is `devin-history`'s job).
- Fixtures contain **synthetic data only** — no real session content is ever
  copied, by design.

## Development

```bash
pip install -e ".[dev]"
pytest
```

Ground rules in [CONTRIBUTING.md](CONTRIBUTING.md): fixtures before parsers,
small commits, bilingual docs.

## License

MIT — see [LICENSE](LICENSE).
