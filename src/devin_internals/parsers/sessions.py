"""Read-only parser for Devin's CLI ``sessions.db``.

Opens the database read-only, gates on :func:`detect_schema_version`, and
returns plain frozen dataclasses — callers never see raw sqlite rows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing_extensions import Self

from dataclasses import dataclass
from pathlib import Path
from typing import Any

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

    def sessions(self, limit: int | None = None) -> list[Session]:
        """All sessions, most recently active first."""
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
        return [
            Session(
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
            for r in self._con.execute(sql, args)
        ]

    def message_nodes(self, session_id: str | None = None) -> list[MessageNode]:
        """Message-forest nodes; optionally scoped to one session."""
        sql = (
            "SELECT row_id, session_id, node_id, parent_node_id, chat_message,"
            " created_at, metadata FROM message_nodes"
        )
        args: tuple[Any, ...] = ()
        if session_id is not None:
            sql += " WHERE session_id = ?"
            args = (session_id,)
        sql += " ORDER BY session_id, node_id"
        return [
            MessageNode(
                row_id=r["row_id"],
                session_id=r["session_id"],
                node_id=r["node_id"],
                parent_node_id=r["parent_node_id"],
                chat_message=r["chat_message"],
                created_at=r["created_at"],
                metadata=r["metadata"],
            )
            for r in self._con.execute(sql, args)
        ]

    def tool_call_state(self, session_id: str | None = None) -> list[ToolCallState]:
        sql = (
            "SELECT session_id, tool_call_id, tool_call_json,"
            " tool_call_update_json FROM tool_call_state"
        )
        args: tuple[Any, ...] = ()
        if session_id is not None:
            sql += " WHERE session_id = ?"
            args = (session_id,)
        return [
            ToolCallState(
                session_id=r["session_id"],
                tool_call_id=r["tool_call_id"],
                tool_call_json=r["tool_call_json"],
                tool_call_update_json=r["tool_call_update_json"],
            )
            for r in self._con.execute(sql, args)
        ]

    def prompt_history(self, session_id: str | None = None) -> list[PromptHistoryEntry]:
        sql = (
            "SELECT id, content, timestamp, session_id, is_shell"
            " FROM prompt_history"
        )
        args: tuple[Any, ...] = ()
        if session_id is not None:
            sql += " WHERE session_id = ?"
            args = (session_id,)
        sql += " ORDER BY timestamp DESC"
        return [
            PromptHistoryEntry(
                id=r["id"],
                content=r["content"],
                timestamp=r["timestamp"],
                session_id=r["session_id"],
                is_shell=bool(r["is_shell"]),
            )
            for r in self._con.execute(sql, args)
        ]

    def rendered_commits(self, session_id: str | None = None) -> list[RenderedCommit]:
        sql = (
            "SELECT id, session_id, sequence_number, rendered_html, created_at"
            " FROM rendered_commits"
        )
        args: tuple[Any, ...] = ()
        if session_id is not None:
            sql += " WHERE session_id = ?"
            args = (session_id,)
        sql += " ORDER BY session_id, sequence_number"
        return [
            RenderedCommit(
                id=r["id"],
                session_id=r["session_id"],
                sequence_number=r["sequence_number"],
                rendered_html=r["rendered_html"],
                created_at=r["created_at"],
            )
            for r in self._con.execute(sql, args)
        ]

    def subagent_heads(self, session_id: str | None = None) -> list[SubagentHead]:
        sql = (
            "SELECT session_id, agent_id, chain_node_id, updated_at"
            " FROM subagent_heads"
        )
        args: tuple[Any, ...] = ()
        if session_id is not None:
            sql += " WHERE session_id = ?"
            args = (session_id,)
        return [
            SubagentHead(
                session_id=r["session_id"],
                agent_id=r["agent_id"],
                chain_node_id=r["chain_node_id"],
                updated_at=r["updated_at"],
            )
            for r in self._con.execute(sql, args)
        ]

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
