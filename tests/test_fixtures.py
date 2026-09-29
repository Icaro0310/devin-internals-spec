"""Fixture-generator tests: the synthetic DBs must be valid and deterministic."""

from __future__ import annotations

import sqlite3

from devin_internals.fixtures import (
    DEFAULT_SEED,
    LATEST_KNOWN_SCHEMA,
    create_acp_messages_db,
    create_sessions_db,
    create_state_vscdb,
)

SESSIONS_TABLES = {
    "sessions",
    "message_nodes",
    "tool_call_state",
    "prompt_history",
    "rendered_commits",
    "subagent_heads",
    "app_state",
    "refinery_schema_history",
}


def _tables(db_path) -> set[str]:
    con = sqlite3.connect(db_path)
    try:
        return {
            r[0]
            for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        con.close()


def _count(db_path, table: str) -> int:
    con = sqlite3.connect(db_path)
    try:
        return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        con.close()


def test_sessions_db_fixture_opens_and_is_populated(tmp_path):
    db = create_sessions_db(tmp_path / "sessions.db")

    assert SESSIONS_TABLES <= _tables(db)
    for table in SESSIONS_TABLES:
        assert _count(db, table) > 0, f"{table} should have synthetic rows"

    con = sqlite3.connect(db)
    try:
        assert con.execute(
            "SELECT MAX(version) FROM refinery_schema_history"
        ).fetchone()[0] == LATEST_KNOWN_SCHEMA
        # foreign keys resolve: every message node belongs to a real session
        orphans = con.execute(
            "SELECT COUNT(*) FROM message_nodes m"
            " LEFT JOIN sessions s ON s.id = m.session_id WHERE s.id IS NULL"
        ).fetchone()[0]
        assert orphans == 0
    finally:
        con.close()


def test_acp_messages_fixture_opens(tmp_path):
    db = create_acp_messages_db(tmp_path / "acp.db")

    assert {"meta", "messages"} <= _tables(db)
    assert _count(db, "meta") > 0
    assert _count(db, "messages") > 0


def test_state_vscdb_fixture_opens(tmp_path):
    db = create_state_vscdb(tmp_path / "state.vscdb")

    assert "ItemTable" in _tables(db)
    assert _count(db, "ItemTable") > 0

    con = sqlite3.connect(db)
    try:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 1
        windsurf_keys = con.execute(
            "SELECT COUNT(*) FROM ItemTable WHERE key LIKE 'windsurfSpace.%'"
        ).fetchone()[0]
        assert windsurf_keys > 0
    finally:
        con.close()


def test_fixtures_are_deterministic(tmp_path):
    a = create_sessions_db(tmp_path / "a" / "sessions.db")
    b = create_sessions_db(tmp_path / "b" / "sessions.db")
    assert a.read_bytes() == b.read_bytes()

    a = create_acp_messages_db(tmp_path / "a" / "acp.db")
    b = create_acp_messages_db(tmp_path / "b" / "acp.db")
    assert a.read_bytes() == b.read_bytes()

    a = create_state_vscdb(tmp_path / "a" / "state.vscdb")
    b = create_state_vscdb(tmp_path / "b" / "state.vscdb")
    assert a.read_bytes() == b.read_bytes()


def test_regeneration_overwrites_cleanly(tmp_path):
    db = create_sessions_db(tmp_path / "sessions.db")
    first = db.read_bytes()
    db = create_sessions_db(tmp_path / "sessions.db", seed=DEFAULT_SEED)
    assert db.read_bytes() == first
