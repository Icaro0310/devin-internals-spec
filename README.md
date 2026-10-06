<div align="center">

<img src="assets/banner.svg" alt="devin-internals-spec" width="100%"/>

<a href="https://github.com/Icaro0310/devin-internals-spec/actions/workflows/tests.yml"><img src="https://github.com/Icaro0310/devin-internals-spec/actions/workflows/tests.yml/badge.svg" alt="tests"/></a>
<a href="https://pypi.org/project/devin-internals-spec/"><img src="https://img.shields.io/pypi/v/devin-internals-spec" alt="PyPI"/></a>
<a href="https://scorecard.dev/viewer/?uri=github.com/Icaro0310/devin-internals-spec"><img src="https://api.scorecard.dev/projects/github.com/Icaro0310/devin-internals-spec/badge" alt="OpenSSF Scorecard"/></a>


<a href="https://github.com/Icaro0310/devin-internals-spec/actions/workflows/ci.yml"><img src="https://github.com/Icaro0310/devin-internals-spec/actions/workflows/ci.yml/badge.svg" alt="ci"/></a>
<a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="License: MIT"/></a>
<a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python 3.10+"/></a>
<a href="https://github.com/Icaro0310/devin-internals-spec/stargazers"><img src="https://img.shields.io/github/stars/Icaro0310/devin-internals-spec" alt="GitHub stars"/></a>
<a href="https://github.com/Icaro0310/devin-internals-spec/commits/main"><img src="https://img.shields.io/github/last-commit/Icaro0310/devin-internals-spec" alt="Last commit"/></a>
<a href="https://github.com/Icaro0310/awesome-devin"><img src="https://img.shields.io/badge/part%20of-devin--*-ecosystem-7c3aed" alt="devin-* ecosystem"/></a>
<a href="https://github.com/Icaro0310/devin-internals-spec/issues"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen" alt="PRs welcome"/></a>
</div>

# devin-internals-spec

**[Linux](README.linux.md)** · **[Personal Windows](README.windows.md)** · **[Corporate Windows](README.corporate-windows.md)**

Part of the [awesome-devin](https://github.com/Icaro0310/awesome-devin) ecosystem: the curated hub for the devin-* tools.

> **Unofficial community project.** Not affiliated with, endorsed by, or
> sponsored by Cognition AI. "Devin" is a trademark of Cognition AI.

**[Windows](README.windows.md)** · **[Linux](README.linux.md)** · English

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

Python ≥ 3.10 and `pipx` are required. **Windows (PowerShell):** install `pipx` with `py -m pip install --user pipx`, run `py -m pipx ensurepath`, then reopen the terminal. **Linux (Debian/Ubuntu):** run `sudo apt install pipx python3-venv` and `pipx ensurepath`; reopen the terminal. Other Linux distributions should install `pipx` using their package manager.

```bash
pipx install "devin-internals-spec==0.3.0"
```

For development:

```bash
pip install -e ".[dev]"
pytest
```

## Usage

```bash
devin-inspect schema   <sessions.db>      # schema-detection contract (JSON)
devin-inspect sessions <sessions.db>      # list sessions (id, title, cwd, …)
devin-inspect health   <devin-data-dir>   # locate + check all three stores
devin-inspect contract <devin-data-dir>   # unified drift check: schema +
                                          # acp meta + usage shape, one report
devin-inspect make-fixture <out>          # deterministic synthetic stores
                                          # for tests/demos (--kind, --seed,
                                          # --schema-version, --n-sessions)
```

`contract` is the single drift boundary for the whole catalog: it reports
`sessions.db` schema version, `acp-messages` meta `schema_version` (observed:
6; 1 on legacy DBs) and unexpected meta keys, and the verified usage shape
(no cost persisted — `num_tokens_preceding` only). On Linux it resolves the
split layout automatically (`~/.local/share/devin` data root +
`~/.config/Devin` GUI root). Exit code is non-zero on any drift.

`AcpMessagesStore.typed_meta()` decodes the `meta` table into a typed
view (`schema_version` normalized to int, `message_count`, `truncated`,
`title` from the `info` JSON blob) with `raw` as fallback.
`devin_internals.projects` gives the canonical project key/path used to
join sessions across tools, and `devin_internals.commits.commit_references()`
extracts git commit SHAs (40-hex + `/commit/<sha>` URLs, with repo context)
from `tool_call_state` payloads — short SHAs are ignored on purpose
(precision over recall for graph joins).

Every subcommand is read-only and accepts `--json`. The Python library is the
supported interface — the CLI is a thin wrapper:

```python
import os
import sys
from pathlib import Path
from devin_internals import detect_schema_version
from devin_internals.parsers import SessionsStore

if os.name == "nt":
    root = Path(os.environ["APPDATA"]) / "devin"
elif sys.platform == "darwin":
    root = Path.home() / "Library" / "Application Support" / "devin"
else:
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    root = data_home / "devin"
sessions_db = root / "cli" / "sessions.db"

detect_schema_version(sessions_db)
# {"schema_version": 17, "known": True, "min_supported": 15, ...}

with SessionsStore(sessions_db) as store:
    store.sessions()  # typed dataclasses
```

## Works with Devin alone (Devin-only mode)

The spec is documentation plus a small local validation library: it reads
Devin's stores to report the schema version and gates tools when the version
is newer than what is known — it stops loudly instead of misparsing. Purely
local; nothing external is needed.

## Platform support

Pure stdlib Python — identical behavior on Windows, Linux and macOS. CI runs
the suite on `windows-latest` + `ubuntu-latest`; the target file or
directory is always an explicit argument, so there are no
platform-specific paths.


### `vscdb-scan` — shape-only audit (IS-1)

`devin-internals vscdb-scan <state.vscdb>` audits the GUI key/value store
and reports, per key: name, value *shape* (json-object/array/string/…),
length, top-level JSON keys and risk flags (`sensitive-key-name`,
`looks-like-jwt`, `large-blob`). **Values are never printed** — flags are
heuristic and recall-biased; a real audit confirmed `state.vscdb` can
hold auth tokens and PII. `--fail-on-flags` exits 1 for CI.

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
small commits, a shared README and Windows/Linux platform guides.

## When to use this

- You are building a tool that reads Devin's local stores and need the documented schema, not reverse-engineering.
- You want a schema-version gate: `detect_schema_version()` refuses loudly on unknown versions instead of misparsing.
- You need deterministic synthetic fixtures to test parsers — no real session data required.
- You need typed, read-only access to `sessions.db` via `SessionsStore` in Python.

## When NOT to use this

- You want to export or dump sessions — this documents and guards the format; `devin-history` does the exporting.
- Your Devin release ships a schema newer than v17 — the detector refuses by design until the spec catches up.
- You need writes — every parser and subcommand is strictly read-only.

## FAQ

**What data does Devin store locally, and where?** Per this spec: a versioned `sessions.db` under `cli/` (sessions, tool-call state, transcripts), one `acp-messages/*.db` per GUI session, a `state.vscdb` KV store with `windsurfSpace.*` keys, `credentials.toml`, and a `refinery_schema_history` migration ledger. The verified details live in `docs/SPEC.md`.

**What happens when Devin ships a new schema version?** Tools using this library fail loudly, not silently. `detect_schema_version()` returns a contract (`known`, `min_supported`) and raises on versions it does not recognize — verified against schema v17 at time of writing.

**How is this different from other sessions.db parsers?** It also documents the Desktop GUI stores (`acp-messages/*.db`, `state.vscdb`, session locks, the migration ledger) that other tools don't cover, and adds the explicit schema-version gate. The library is the supported interface; `devin-inspect` is a thin CLI wrapper.

## License

MIT — see [LICENSE](LICENSE).


---

If this saved you debugging time, a ⭐ on the repo helps others find it.
