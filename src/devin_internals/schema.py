"""Schema-version detection for Devin's ``sessions.db``.

The detector is the safety gate: it reads ``refinery_schema_history`` (the
migration ledger) and ``app_state.schema_compat_version`` and refuses — loudly
— anything it has never seen, so parsers never silently misread a new schema.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

MIN_SUPPORTED_SCHEMA = 15
LATEST_KNOWN_SCHEMA = 17

SCHEMA_COMPAT_KEY = "schema_compat_version"


class SchemaError(RuntimeError):
    """Base class for schema-detection failures."""


class SchemaDetectionError(SchemaError):
    """The file exists but does not look like a Devin ``sessions.db``."""


class UnknownSchemaVersionError(SchemaError):
    """The schema version is outside the range this library knows about."""

    def __init__(self, version: int, path: Path) -> None:
        self.version = version
        self.path = path
        super().__init__(
            f"{path}: sessions.db schema version {version} is unknown to "
            f"devin-internals-spec (known range: 1..{LATEST_KNOWN_SCHEMA}). "
            "Refusing to parse — update the spec/library before reading this file."
        )


def _connect_readonly(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def detect_schema_version(db_path: str | Path) -> dict[str, Any]:
    """Detect the schema version of a ``sessions.db``.

    Returns the version contract::

        {"schema_version": 17, "known": True, "min_supported": 15, ...}

    Raises:
        SchemaDetectionError: file missing, or missing the expected tables.
        UnknownSchemaVersionError: version outside the known range 1..17.
    """
    path = Path(db_path).expanduser()
    if not path.exists():
        raise SchemaDetectionError(f"{path}: no such file")
    if path.is_dir():
        raise SchemaDetectionError(f"{path}: is a directory, not a sessions.db")

    con = _connect_readonly(path)
    try:
        tables = {
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if "refinery_schema_history" not in tables:
            raise SchemaDetectionError(
                f"{path}: missing refinery_schema_history — "
                "not a Devin sessions.db (or pre-versioning format)"
            )

        version = con.execute(
            "SELECT MAX(version) FROM refinery_schema_history"
        ).fetchone()[0]
        if version is None:
            raise SchemaDetectionError(
                f"{path}: refinery_schema_history is empty — "
                "cannot determine schema version"
            )
        version = int(version)

        compat_version: int | None = None
        if "app_state" in tables:
            row = con.execute(
                "SELECT value FROM app_state WHERE key = ?", (SCHEMA_COMPAT_KEY,)
            ).fetchone()
            if row is not None:
                try:
                    compat_version = int(row[0])
                except (TypeError, ValueError):
                    compat_version = None

        if version < 1 or version > LATEST_KNOWN_SCHEMA:
            raise UnknownSchemaVersionError(version, path)

        return {
            "schema_version": version,
            "schema_compat_version": compat_version,
            "known": True,
            "supported": MIN_SUPPORTED_SCHEMA <= version <= LATEST_KNOWN_SCHEMA,
            "verified": version == LATEST_KNOWN_SCHEMA,
            "min_supported": MIN_SUPPORTED_SCHEMA,
            "max_supported": LATEST_KNOWN_SCHEMA,
        }
    finally:
        con.close()
