"""Read-only parser for Devin Desktop's per-session ``acp-messages/*.db``.

These stores have no ``refinery_schema_history`` ledger, so the parser gates
on table shape (``meta`` + ``messages``) instead of a version number.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from devin_internals.parsers._common import connect_readonly, require_tables
from devin_internals.schema import SchemaDetectionError


@dataclass(frozen=True)
class AcpMessage:
    position: int
    kind: str
    payload: str


class AcpMessagesStore:
    """Read-only handle on one ``acp-messages/*.db`` file."""

    REQUIRED_TABLES = {"meta", "messages"}

    def __init__(self, db_path: str | Path) -> None:
        self.path = Path(db_path).expanduser()
        if not self.path.exists():
            raise SchemaDetectionError(f"{self.path}: no such file")
        self._con = connect_readonly(self.path)
        require_tables(self._con, self.path, self.REQUIRED_TABLES)

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> "AcpMessagesStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def meta(self) -> dict[str, str]:
        """All ``meta`` key/value pairs.

        The set of keys is not documented upstream — callers should treat the
        key space as open and tolerate unknown keys.
        """
        return {
            r["key"]: r["value"]
            for r in self._con.execute("SELECT key, value FROM meta ORDER BY key")
        }

    def messages(self) -> list[AcpMessage]:
        """All messages in ``position`` order."""
        return [
            AcpMessage(
                position=r["position"], kind=r["kind"], payload=r["payload"]
            )
            for r in self._con.execute(
                "SELECT position, kind, payload FROM messages ORDER BY position"
            )
        ]

    def counts(self) -> dict[str, int]:
        return {
            t: self._con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in sorted(self.REQUIRED_TABLES)
        }
