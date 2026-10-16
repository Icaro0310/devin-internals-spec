"""Materialize the install-state fixture corpus (docs/SURFACE-HEALTH.md §7).

``build_install_states(root)`` writes deterministic *installation-state*
trees — one per ``(surface, state)`` — plus ``install-states-manifest.json``
declaring the ordered check-ladder findings a conformant doctor must report
per fixture. The committed copy at ``fixtures/install-states/`` is the
vendored artifact the doctor's test suite consumes.

Distinct from ``session_corpus``: those fixtures are *content-bearing*
session stores judged by ``SessionMeta``/``SessionEvidence`` output; these
are *installation substrate* — the same store roots in healthy, absent,
empty, corrupt and versioned states, judged by SURFACE-HEALTH findings.
Fixture bytes are minimal: only what each rung needs to see (a sqlite with
the right tables/ledger, a tiny jsonl/json, an empty file, an empty dir).

Each fixture dir is a *root surrogate* holding the surface's
SESSION-SURFACES §6-relative store layout (``devin/cli/sessions.db``,
``Devin/User/acp-messages/*.db``, ``.copilot/session-state/…``,
``.codex/state_*.sqlite``, ``Code/User/workspaceStorage/*/chatSessions/…``),
so an ``absent`` fixture is an empty dir plus ``.gitkeep`` — no candidate
root exists at all.

The ``expected_findings`` blocks are hand-derived from the spec's ladder
semantics (§2): ``present`` → ``readable`` → ``schema`` → ``sane``; the
first FAIL stops the ladder; rungs with nothing to evaluate emit nothing;
``not-installed`` is a PASS-level note, never a failure. ``locked-or-
unreadable`` is deliberately unmodeled — no deterministic cross-platform
fixture exists (§7).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from pathlib import Path

from devin_internals import fixtures
from devin_internals.fixtures import (
    _CORPUS_T0_MS,
    CODEX_THREADS_DDL,
    DEFAULT_SEED,
    LATEST_KNOWN_SCHEMA,
    MIN_SUPPORTED_SCHEMA,
    _copilot_event,
    _copilot_workspace_yaml,
    _fake_uuid,
    _ws_dir_name,
)

# Closed vocabularies from SURFACE-HEALTH §2/§5 — pinned so a typo in the
# manifest can't silently widen the contract (same discipline as
# session_corpus.ALLOWED_WARNING_CODES).
SURFACES = ("vscode-chat", "copilot-cli", "codex-cli", "devin-cli", "devin-chat")
CHECKS = ("present", "readable", "schema", "sane")
STATUSES = ("PASS", "WARN", "FAIL")
ALLOWED_FINDING_CODES = frozenset(
    {
        "store-missing",
        "store-corrupt",
        "unreadable",
        "schema-old",
        "schema-unknown",
        "empty-store",
        "store-empty",
    }
)
ALLOWED_NOTES = frozenset({"not-installed"})

# States the corpus models per surface (SURFACE-HEALTH §7). `absent` is
# modeled for every surface — for a doctor, "agent not installed" is always
# a meaningful environment. `schema-old` exists only for devin-cli: it is
# the sole surface with a version ordering below the known floor.
# `missing-store` covers both store shapes: a file artifact missing under
# an existing root (devin-cli) and a directory store missing under an
# existing root (copilot-cli).
_PLAN: dict[str, list[str]] = {
    "devin-cli": [
        "healthy",
        "absent",
        "missing-store",
        "empty-store",
        "corrupt-store",
        "schema-old",
        "schema-unknown",
    ],
    "devin-chat": [
        "healthy",
        "absent",
        "empty-store",
        "corrupt-store",
        "schema-unknown",
    ],
    "copilot-cli": [
        "healthy",
        "absent",
        "missing-store",
        "empty-store",
        "corrupt-store",
        "schema-unknown",
    ],
    "codex-cli": [
        "healthy",
        "absent",
        "empty-store",
        "corrupt-store",
        "schema-unknown",
    ],
    "vscode-chat": [
        "healthy",
        "absent",
        "empty-store",
        "corrupt-store",
        "schema-unknown",
    ],
}

# `empty-store` resolves to `empty-store` (zero-byte store file) or
# `store-empty` (store container holds nothing) per fixture shape — §5.
_EMPTY_CODE = {
    "devin-cli": "empty-store",  # zero-byte sessions.db
    "codex-cli": "empty-store",  # zero-byte state_4.sqlite
    "devin-chat": "store-empty",  # acp-messages/ exists, holds no .db
    "copilot-cli": "store-empty",  # session-state/ exists, holds nothing
    "vscode-chat": "store-empty",  # chatSessions/ exists, holds nothing
}

_CORRUPT_SQLITE = b"fixture: not a sqlite database\n"
_CORRUPT_JSON = b'{ "fixture": corrupt json\n'


def _finding(check: str, status: str, code: str | None = None,
             note: str | None = None) -> dict:
    assert check in CHECKS, check
    assert status in STATUSES, status
    f: dict = {"check": check, "status": status}
    if code is not None:
        assert code in ALLOWED_FINDING_CODES, code
        f["code"] = code
    if note is not None:
        assert note in ALLOWED_NOTES, note
        f["note"] = note
    return f


def _expected(surface: str, state: str) -> list[dict]:
    """Hand-derived expected ladder output per SURFACE-HEALTH §2 semantics."""
    if state == "healthy":
        findings = [
            _finding("present", "PASS"),
            _finding("readable", "PASS"),
            _finding("schema", "PASS"),
            _finding("sane", "PASS"),
        ]
    elif state == "absent":
        findings = [_finding("present", "PASS", note="not-installed")]
    elif state == "missing-store":
        findings = [_finding("present", "WARN", code="store-missing")]
    elif state == "corrupt-store":
        findings = [
            _finding("present", "PASS"),
            _finding("readable", "FAIL", code="store-corrupt"),
        ]
    elif state == "schema-old":
        findings = [
            _finding("present", "PASS"),
            _finding("readable", "PASS"),
            _finding("schema", "WARN", code="schema-old"),
            _finding("sane", "PASS"),
        ]
    elif state == "schema-unknown":
        findings = [
            _finding("present", "PASS"),
            _finding("readable", "PASS"),
            _finding("schema", "WARN", code="schema-unknown"),
            _finding("sane", "PASS"),
        ]
    elif state == "empty-store":
        # readable/schema emit nothing — nothing to evaluate (§2); sane
        # owns the "empty" verdict.
        findings = [
            _finding("present", "PASS"),
            _finding("sane", "WARN", code=_EMPTY_CODE[surface]),
        ]
    else:  # pragma: no cover - _PLAN pins the state set
        raise AssertionError(f"unmodeled state {state!r}")
    order = {c: i for i, c in enumerate(CHECKS)}
    assert [order[f["check"]] for f in findings] == sorted(
        order[f["check"]] for f in findings
    ), f"{surface}/{state}: findings out of ladder order"
    return findings


def _write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _write_text(path: Path, text: str) -> Path:
    # Bytes, not write_text: corpus output must stay LF-stable on Windows.
    return _write(path, text.encode("utf-8"))


def _absent(state_dir: Path) -> None:
    # No candidate root at all — the dir exists only so git tracks it.
    _write(state_dir / ".gitkeep", b"")


def _empty_dir(path: Path) -> None:
    """An existing-but-empty store container (§3.4 `store-empty`). The
    ``.gitkeep`` keeps git tracking the otherwise-empty dir and is not a
    store artifact — the present rung ignores it."""
    path.mkdir(parents=True, exist_ok=True)
    _write(path / ".gitkeep", b"")


def _valid_sqlite(path: Path, ddl: str, rows: list[tuple], table: str,
                  columns: int) -> Path:
    """A minimal valid sqlite store: the right DDL plus ``rows``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    try:
        with con:
            con.executescript(ddl)
            for row in rows:
                assert len(row) == columns
                con.execute(
                    f"INSERT INTO {table} VALUES ({', '.join('?' * columns)})",
                    row,
                )
    finally:
        con.close()
    return path


def _build_devin_cli(state_dir: Path, state: str, seed: int) -> None:
    db = state_dir / "devin" / "cli" / "sessions.db"
    if state == "absent":
        _absent(state_dir)
    elif state == "missing-store":
        # The data root exists (credentials.toml is a real sibling file,
        # devin_internals.paths) but cli/sessions.db was never written.
        _write_text(state_dir / "devin" / "credentials.toml",
                    "[fixture]\nsynthetic = true\n")
    elif state == "empty-store":
        _write(db, b"")
    elif state == "corrupt-store":
        _write(db, _CORRUPT_SQLITE)
    else:
        version = {
            "healthy": LATEST_KNOWN_SCHEMA,
            # ledger MAX(version) below MIN_SUPPORTED_SCHEMA → schema-old
            "schema-old": MIN_SUPPORTED_SCHEMA - 1,
            # ledger MAX(version) above LATEST_KNOWN_SCHEMA → schema-unknown
            "schema-unknown": 99,
        }[state]
        fixtures.create_sessions_db(db, schema_version=version,
                                    seed=seed, n_sessions=2)


def _build_devin_chat(state_dir: Path, state: str, seed: int) -> None:
    acp_dir = state_dir / "Devin" / "User" / "acp-messages"
    if state == "absent":
        _absent(state_dir)
    elif state == "empty-store":
        _empty_dir(acp_dir)
    elif state == "corrupt-store":
        _write(acp_dir / f"{_fake_uuid(seed, 'acp-corrupt')}.db",
               _CORRUPT_SQLITE)
    elif state == "schema-unknown":
        # A readable sqlite that is not an ACP store — meta/messages absent.
        _valid_sqlite(acp_dir / f"{_fake_uuid(seed, 'acp-unknown')}.db",
                      "CREATE TABLE fixture_other(key TEXT PRIMARY KEY);",
                      [], "fixture_other", 1)
    else:
        fixtures.create_acp_messages_db(
            acp_dir / f"{_fake_uuid(seed, 'acp-healthy')}.db", seed=seed
        )


def _build_copilot_cli(state_dir: Path, state: str, seed: int) -> None:
    session_state = state_dir / ".copilot" / "session-state"
    if state == "absent":
        _absent(state_dir)
    elif state == "missing-store":
        # The copilot home exists (a config file, unrelated) but no
        # session-state/ or history-session-state/ store was ever created.
        _write_text(state_dir / ".copilot" / "config.toml",
                    "[fixture]\nsynthetic = true\n")
    elif state == "empty-store":
        _empty_dir(session_state)
    else:
        sid = _fake_uuid(seed, f"copilot-{state}")
        events_file = session_state / sid / "events.jsonl"
        if state == "corrupt-store":
            _write(events_file, _CORRUPT_JSON)
        elif state == "schema-unknown":
            # Valid JSON, but not the §6.3 envelope.
            _write_text(events_file, '{"version": 99, "records": []}\n')
        else:
            t = _CORPUS_T0_MS
            lines = [
                json.dumps(
                    _copilot_event(1, None, t, "session.start",
                                   {"id": sid, "version": "0.0.0-fixture"})
                ),
                json.dumps(
                    _copilot_event(2, "evt-0001", t + 5_000,
                                   "session.shutdown",
                                   {"reason": "fixture-close"})
                ),
            ]
            _write_text(events_file, "\n".join(lines) + "\n")
            _write_text(events_file.parent / "workspace.yaml",
                        _copilot_workspace_yaml("/fixture/workspace/health"))


def _build_codex_cli(state_dir: Path, state: str, seed: int) -> None:
    db = state_dir / ".codex" / "state_4.sqlite"
    if state == "absent":
        _absent(state_dir)
    elif state == "empty-store":
        _write(db, b"")
    elif state == "corrupt-store":
        _write(db, _CORRUPT_SQLITE)
    elif state == "schema-unknown":
        # Readable sqlite, numeric suffix — but no `threads` table.
        _valid_sqlite(db, "CREATE TABLE fixture_other(key TEXT PRIMARY KEY);",
                      [], "fixture_other", 1)
    else:
        _valid_sqlite(
            db,
            CODEX_THREADS_DDL,
            [(_fake_uuid(seed, "codex-healthy"), _CORPUS_T0_MS,
              _CORPUS_T0_MS + 60_000, "/fixture/workspace/codex-health", 1)],
            "threads",
            5,
        )


def _build_vscode_chat(state_dir: Path, state: str, seed: int) -> None:
    chat_sessions = (
        state_dir / "Code" / "User" / "workspaceStorage"
        / _ws_dir_name(seed, f"vscode-{state}") / "chatSessions"
    )
    if state == "absent":
        _absent(state_dir)
    elif state == "empty-store":
        _empty_dir(chat_sessions)
    else:
        session_file = chat_sessions / f"{_fake_uuid(seed, f'vscode-{state}')}.json"
        if state == "corrupt-store":
            _write(session_file, _CORRUPT_JSON)
        elif state == "schema-unknown":
            # Parses fine but carries none of the §6.5 recognizable keys.
            _write_text(session_file, '{"unknown_format": true}\n')
        else:
            doc = {
                "version": 3,
                "sessionId": _fake_uuid(seed, "vscode-healthy"),
                "creationDate": _CORPUS_T0_MS,
                "requests": [
                    {"requestId": "req-1", "timestamp": _CORPUS_T0_MS + 5_000}
                ],
            }
            _write_text(session_file, json.dumps(doc, indent=2) + "\n")


_BUILDERS = {
    "devin-cli": _build_devin_cli,
    "devin-chat": _build_devin_chat,
    "copilot-cli": _build_copilot_cli,
    "codex-cli": _build_codex_cli,
    "vscode-chat": _build_vscode_chat,
}

# Same LF/binary contract as fixtures/session-corpus/.gitattributes — the
# drift test byte-compares the vendored corpus across platforms.
_GITATTRIBUTES = """\
# Corpus artifacts are LF-canonical: the drift test compares bytes across
# platforms, so checkouts must never CRLF-ify text files even when the
# runner sets core.autocrlf=true. The sqlite stores are binary.
* text eol=lf
*.sqlite -text
*.db -text
"""

# The repo-level .gitignore blanket-ignores `*.db` (real Devin stores are
# local-only and never committed); this corpus vendors *synthetic* .db
# stores, so it carries its own un-ignore — the same self-contained
# discipline as .gitattributes (it travels with vendored copies too).
_GITIGNORE = """\
# This corpus vendors generated *.db fixtures — re-include them against the
# repo-level `*.db` ignore. These are synthetic stores, never real data.
!*.db
"""


def build_install_states(root: str | Path, *, seed: int = DEFAULT_SEED) -> Path:
    """Write the deterministic install-state corpus under ``root`` and return
    the manifest path. ``root`` is (re)created wholesale — the directory is
    owned by the generator, mirroring ``build_session_corpus``."""
    root = Path(root)
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    fixture_entries: list[dict] = []
    for surface in SURFACES:
        for state in _PLAN[surface]:
            store_path = f"{surface}/{state}"
            _BUILDERS[surface](root / surface / state, state, seed)
            fixture_entries.append(
                {
                    "surface": surface,
                    "state": state,
                    "store_path": store_path,
                    "expected_findings": _expected(surface, state),
                }
            )
    fixture_entries.sort(key=lambda f: (f["surface"], f["state"]))

    manifest = {
        "version": 1,
        "spec": "docs/SURFACE-HEALTH.md",
        "unmodeled_states": {
            "locked-or-unreadable": (
                "not deterministically reproducible: POSIX mode bits are "
                "advisory on Windows runners and OS/SQLite locks are "
                "timing-dependent — no stable fixture exists (§7)"
            ),
        },
        "fixtures": fixture_entries,
    }

    (root / ".gitattributes").write_bytes(_GITATTRIBUTES.encode("utf-8"))
    (root / ".gitignore").write_bytes(_GITIGNORE.encode("utf-8"))
    path = root / "install-states-manifest.json"
    path.write_bytes((json.dumps(manifest, indent=2) + "\n").encode("utf-8"))
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m devin_internals.install_states",
        description="Regenerate the deterministic install-state fixture "
        "corpus (docs/SURFACE-HEALTH.md §7).",
    )
    parser.add_argument("outdir", type=Path, help="corpus output directory")
    args = parser.parse_args(argv)
    manifest = build_install_states(args.outdir)
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
