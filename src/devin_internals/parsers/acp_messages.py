"""Read-only parser for Devin Desktop's per-session ``acp-messages/*.db``.

These stores have no ``refinery_schema_history`` ledger, so the parser gates
on table shape (``meta`` + ``messages``) instead of a version number.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from typing_extensions import Self

from devin_internals.parsers._common import connect_readonly, require_tables
from devin_internals.schema import SchemaDetectionError

KNOWN_ACP_SCHEMA_VERSIONS = frozenset({1, 6})


@dataclass(frozen=True)
class AcpMessage:
    position: int
    kind: str
    payload: str


@dataclass(frozen=True)
class AcpMeta:
    """Typed view over the ``meta`` table of an acp-messages store.

    ``schema_version`` is observed as TEXT ``"1"`` (legacy) or ``"6"`` in
    the wild and is normalized to int. ``title`` comes from the ``info``
    JSON blob when present. Unknown keys stay available via ``raw``.
    """

    schema_version: int | None
    message_count: int | None
    truncated: bool
    title: str | None
    info: dict
    raw: dict[str, str]

    @property
    def known_schema(self) -> bool:
        return self.schema_version in KNOWN_ACP_SCHEMA_VERSIONS


def _to_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class AcpMessagesStore:
    """Read-only handle on one ``acp-messages/*.db`` file."""

    REQUIRED_TABLES: ClassVar[set[str]] = {"meta", "messages"}

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

    def meta(self) -> dict[str, str]:
        """All ``meta`` key/value pairs.

        The set of keys is not documented upstream — callers should treat the
        key space as open and tolerate unknown keys.
        """
        return {
            r["key"]: r["value"]
            for r in self._con.execute("SELECT key, value FROM meta ORDER BY key")
        }

    def typed_meta(self) -> AcpMeta:
        """The ``meta`` table decoded into known fields + raw fallback."""
        raw = self.meta()
        try:
            info = json.loads(raw.get("info") or "{}")
            if not isinstance(info, dict):
                info = {}
        except json.JSONDecodeError:
            info = {}
        title = info.get("title")
        return AcpMeta(
            schema_version=_to_int(raw.get("schema_version")),
            message_count=_to_int(raw.get("message_count")),
            truncated=raw.get("truncated") not in (None, "0", "false"),
            title=title if isinstance(title, str) else None,
            info=info,
            raw=raw,
        )

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
