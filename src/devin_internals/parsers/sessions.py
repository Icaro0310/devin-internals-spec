"""Read-only parser for Devin's CLI ``sessions.db``.

Opens the database read-only, gates on :func:`detect_schema_version`, and
returns plain frozen dataclasses — callers never see raw sqlite rows.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from typing_extensions import Self

from devin_internals.parsers._common import connect_readonly
from devin_internals.schema import (
    LATEST_KNOWN_SCHEMA,
    MIN_SUPPORTED_SCHEMA,
    SchemaError,
    detect_schema_version,
)


@dataclass(frozen=True)
class Session:
    id: str
    working_directory: str
    backend_type: str
    model: str
    agent_mode: str
    created_at: int
    last_activity_at: int
    title: str | None
    main_chain_id: int | None
    shell_last_seen_index: int | None
    cogs_json: str | None
    workspace_dirs: str | None
    hidden: bool
    metadata: str | None

    @property
    def status(self) -> str:
        return "hidden" if self.hidden else "active"


@dataclass(frozen=True)
class MessageNode:
    row_id: int
    session_id: str
    node_id: int
    parent_node_id: int | None
    chat_message: str
    created_at: int
    metadata: str | None


@dataclass(frozen=True)
class ToolCallState:
    session_id: str
    tool_call_id: str
    tool_call_json: str | None
    tool_call_update_json: str | None


@dataclass(frozen=True)
class PromptHistoryEntry:
    id: int
    content: str
    timestamp: int
    session_id: str
    is_shell: bool


@dataclass(frozen=True)
class RenderedCommit:
    id: int
    session_id: str
    sequence_number: int
    rendered_html: str
    created_at: int


@dataclass(frozen=True)
class SubagentHead:
    session_id: str
    agent_id: str
    chain_node_id: int
    updated_at: int


SESSIONS_TABLES = (
    "sessions",
    "message_nodes",
    "tool_call_state",
    "prompt_history",
    "rendered_commits",
    "subagent_heads",
    "app_state",
    "refinery_schema_history",
)

# Integer primary keys usable as append-only high-water marks by
# incremental consumers (tool_call_state/subagent_heads have composite
# keys, sessions/app_state text keys — they are absent on purpose).
_MAX_ID_COLUMNS = {
    "message_nodes": "row_id",
    "prompt_history": "id",
    "rendered_commits": "id",
}

_T = TypeVar("_T")


def _session_row(r: Any) -> Session:
    return Session(
        id=r["id"],
        working_directory=r["working_directory"],
        backend_type=r["backend_type"],
        model=r["model"],
        agent_mode=r["agent_mode"],
        created_at=r["created_at"],
        last_activity_at=r["last_activity_at"],
        title=r["title"],
        main_chain_id=r["main_chain_id"],
        shell_last_seen_index=r["shell_last_seen_index"],
        cogs_json=r["cogs_json"],
        workspace_dirs=r["workspace_dirs"],
        hidden=bool(r["hidden"]),
        metadata=r["metadata"],
    )


def _message_node_row(r: Any) -> MessageNode:
    return MessageNode(
        row_id=r["row_id"],
        session_id=r["session_id"],
        node_id=r["node_id"],
        parent_node_id=r["parent_node_id"],
        chat_message=r["chat_message"],
        created_at=r["created_at"],
        metadata=r["metadata"],
    )


def _tool_call_state_row(r: Any) -> ToolCallState:
    return ToolCallState(
        session_id=r["session_id"],
        tool_call_id=r["tool_call_id"],
        tool_call_json=r["tool_call_json"],
        tool_call_update_json=r["tool_call_update_json"],
    )


def _prompt_history_row(r: Any) -> PromptHistoryEntry:
    return PromptHistoryEntry(
        id=r["id"],
        content=r["content"],
        timestamp=r["timestamp"],
        session_id=r["session_id"],
        is_shell=bool(r["is_shell"]),
    )


def _rendered_commit_row(r: Any) -> RenderedCommit:
    return RenderedCommit(
        id=r["id"],
        session_id=r["session_id"],
        sequence_number=r["sequence_number"],
        rendered_html=r["rendered_html"],
        created_at=r["created_at"],
    )


def _subagent_head_row(r: Any) -> SubagentHead:
    return SubagentHead(
        session_id=r["session_id"],
        agent_id=r["agent_id"],
        chain_node_id=r["chain_node_id"],
        updated_at=r["updated_at"],
    )


class SessionsStore:
    """Read-only handle on a ``sessions.db``.

    Raises:
        SchemaDetectionError: file missing or not a sessions.db.
        UnknownSchemaVersionError: schema version newer than v17.
        SchemaError: schema version known but below ``min_supported``.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.path = Path(db_path).expanduser()
        self.schema_info = detect_schema_version(self.path)
        version = self.schema_info["schema_version"]
        if not self.schema_info["supported"]:
            raise SchemaError(
                f"{self.path}: schema version {version} is known but "
                f"unsupported (supported range: {MIN_SUPPORTED_SCHEMA}.."
                f"{LATEST_KNOWN_SCHEMA}) — refusing to parse"
            )
        self._con = connect_readonly(self.path)

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- table parsers ------------------------------------------------------
    #
    # Every ``iter_*`` method streams rows via ``cursor.fetchmany`` so
    # callers never pay for a fully materialized table; the list-returning
    # counterparts simply drain the matching iterator and stay the
    # backward-compatible API.

    def _stream(
        self,
        sql: str,
        args: tuple[Any, ...],
        factory: Callable[[Any], _T],
        batch_size: int,
    ) -> Iterator[_T]:
        """Yield ``factory(row)`` lazily, ``batch_size`` rows at a time."""
        if batch_size < 1:
            raise ValueError(
                f"batch_size must be >= 1, got {batch_size} — "
                "fetchmany(0) drains the whole table and defeats streaming"
            )
        cur = self._con.execute(sql, args)
        while batch := cur.fetchmany(batch_size):
            for row in batch:
                yield factory(row)

    def sessions(self, limit: int | None = None) -> list[Session]:
        """All sessions, most recently active first."""
        return list(self.iter_sessions(limit=limit))

    def iter_sessions(
        self, limit: int | None = None, batch_size: int = 2000
    ) -> Iterator[Session]:
        """Stream sessions, most recently active first."""
        sql = (
            "SELECT id, working_directory, backend_type, model, agent_mode,"
            " created_at, last_activity_at, title, main_chain_id,"
            " shell_last_seen_index, cogs_json, workspace_dirs, hidden, metadata"
            " FROM sessions ORDER BY last_activity_at DESC"
        )
        args: tuple[Any, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            args = (limit,)
        yield from self._stream(sql, args, _session_row, batch_size)

    def message_nodes(self, session_id: str | None = None) -> list[MessageNode]:
        """Message-forest nodes; optionally scoped to one session."""
        return list(self.iter_message_nodes(session_id=session_id))

    def iter_message_nodes(
        self, session_id: str | None = None, batch_size: int = 2000
    ) -> Iterator[MessageNode]:
        """Stream message-forest nodes; optionally scoped to one session."""
        sql = (
            "SELECT row_id, session_id, node_id, parent_node_id, chat_message,"
            " created_at, metadata FROM message_nodes"
        )
        args: tuple[Any, ...] = ()
        if session_id is not None:
            sql += " WHERE session_id = ?"
            args = (session_id,)
        sql += " ORDER BY session_id, node_id"
        yield from self._stream(sql, args, _message_node_row, batch_size)

    def tool_call_state(self, session_id: str | None = None) -> list[ToolCallState]:
        return list(self.iter_tool_call_state(session_id=session_id))

    def iter_tool_call_state(
        self, session_id: str | None = None, batch_size: int = 2000
    ) -> Iterator[ToolCallState]:
        """Stream tool_call_state rows; optionally scoped to one session."""
        sql = (
            "SELECT session_id, tool_call_id, tool_call_json,"
            " tool_call_update_json FROM tool_call_state"
        )
        args: tuple[Any, ...] = ()
        if session_id is not None:
            sql += " WHERE session_id = ?"
            args = (session_id,)
        yield from self._stream(sql, args, _tool_call_state_row, batch_size)

    def prompt_history(self, session_id: str | None = None) -> list[PromptHistoryEntry]:
        return list(self.iter_prompt_history(session_id=session_id))

    def iter_prompt_history(
        self, session_id: str | None = None, batch_size: int = 2000
    ) -> Iterator[PromptHistoryEntry]:
        """Stream prompt_history rows, newest first."""
        sql = (
            "SELECT id, content, timestamp, session_id, is_shell"
            " FROM prompt_history"
        )
        args: tuple[Any, ...] = ()
        if session_id is not None:
            sql += " WHERE session_id = ?"
            args = (session_id,)
        sql += " ORDER BY timestamp DESC"
        yield from self._stream(sql, args, _prompt_history_row, batch_size)

    def rendered_commits(self, session_id: str | None = None) -> list[RenderedCommit]:
        return list(self.iter_rendered_commits(session_id=session_id))

    def iter_rendered_commits(
        self, session_id: str | None = None, batch_size: int = 2000
    ) -> Iterator[RenderedCommit]:
        """Stream rendered_commits rows; optionally scoped to one session."""
        sql = (
            "SELECT id, session_id, sequence_number, rendered_html, created_at"
            " FROM rendered_commits"
        )
        args: tuple[Any, ...] = ()
        if session_id is not None:
            sql += " WHERE session_id = ?"
            args = (session_id,)
        sql += " ORDER BY session_id, sequence_number"
        yield from self._stream(sql, args, _rendered_commit_row, batch_size)

    def subagent_heads(self, session_id: str | None = None) -> list[SubagentHead]:
        return list(self.iter_subagent_heads(session_id=session_id))

    def iter_subagent_heads(
        self, session_id: str | None = None, batch_size: int = 2000
    ) -> Iterator[SubagentHead]:
        """Stream subagent_heads rows; optionally scoped to one session."""
        sql = (
            "SELECT session_id, agent_id, chain_node_id, updated_at"
            " FROM subagent_heads"
        )
        args: tuple[Any, ...] = ()
        if session_id is not None:
            sql += " WHERE session_id = ?"
            args = (session_id,)
        yield from self._stream(sql, args, _subagent_head_row, batch_size)

    def app_state(self) -> dict[str, str]:
        return {
            r["key"]: r["value"]
            for r in self._con.execute("SELECT key, value FROM app_state")
        }

    def counts(self) -> dict[str, int]:
        """Row count per sessions.db table (for health reporting)."""
        return {
            t: self._con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in SESSIONS_TABLES
        }

    def max_ids(self) -> dict[str, int]:
        """Highest integer primary key per append-only table (0 when empty).

        Incremental consumers persist these as watermarks: a max that
        drops below a previously recorded watermark means the source
        table was pruned and the watermark is invalid.
        """
        return {
            table: self._con.execute(
                f"SELECT COALESCE(MAX({column}), 0) FROM {table}"
            ).fetchone()[0]
            for table, column in _MAX_ID_COLUMNS.items()
        }
