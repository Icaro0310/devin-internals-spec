"""Shared plumbing for the per-store parsers.

Every parser opens its database read-only and validates the store before
handing out records — ``sessions.db`` via the schema-version detector, the
ledger-less stores (acp-messages, state.vscdb) via a table-shape check.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from devin_internals.schema import SchemaDetectionError


def connect_readonly(path: str | Path) -> sqlite3.Connection:
    """Open ``path`` read-only with ``sqlite3.Row`` access."""
    path = Path(path).expanduser()
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def require_tables(
    con: sqlite3.Connection, path: Path, required: set[str]
) -> None:
    """Raise :class:`SchemaDetectionError` unless all ``required`` tables exist."""
    tables = {
        row[0]
        for row in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    missing = sorted(required - tables)
    if missing:
        raise SchemaDetectionError(
            f"{path}: missing table(s) {', '.join(missing)} — "
            "not the expected Devin store (or an unknown layout)"
        )
