"""Read-only parser for Devin Desktop's ``globalStorage/state.vscdb``.

A VS Code-style ``ItemTable`` key/value store. Values are declared BLOB but
hold text in practice — they are decoded as UTF-8 (``errors="replace"``) so
callers always get ``str`` back.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from typing_extensions import Self

from devin_internals.parsers._common import connect_readonly, require_tables
from devin_internals.schema import SchemaDetectionError

WINDSURF_PREFIX = "windsurfSpace."


class StateVscdbStore:
    """Read-only handle on a ``state.vscdb`` file."""

    REQUIRED_TABLES: ClassVar[set[str]] = {"ItemTable"}

    def __init__(self, db_path: str | Path) -> None:
        self.path = Path(db_path).expanduser()
        if not self.path.exists():
            raise SchemaDetectionError(f"{self.path}: no such file")
        self._con = connect_readonly(self.path)
        require_tables(self._con, self.path, self.REQUIRED_TABLES)

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @staticmethod
    def _decode(value: object) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    def get(self, key: str) -> str | None:
        """Return the decoded value for ``key``, or ``None`` if absent."""
        row = self._con.execute(
            "SELECT value FROM ItemTable WHERE key = ?", (key,)
        ).fetchone()
        return None if row is None else self._decode(row["value"])

    def list_prefix(self, prefix: str = WINDSURF_PREFIX) -> dict[str, str]:
        """All key/value pairs whose key starts with ``prefix``."""
        return {
            r["key"]: self._decode(r["value"])
            for r in self._con.execute(
                "SELECT key, value FROM ItemTable WHERE key LIKE ?"
                " ORDER BY key",
                (f"{prefix}%",),
            )
        }

    def keys(self) -> list[str]:
        return [
            r["key"]
            for r in self._con.execute("SELECT key FROM ItemTable ORDER BY key")
        ]

    def counts(self) -> dict[str, int]:
        return {
            "ItemTable": self._con.execute(
                "SELECT COUNT(*) FROM ItemTable"
            ).fetchone()[0]
        }
