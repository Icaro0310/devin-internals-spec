"""Parser tests: every store returns typed records from the M1 fixtures."""

from __future__ import annotations

import pytest

from devin_internals import SchemaDetectionError, SchemaError, UnknownSchemaVersionError
from devin_internals.fixtures import (
    create_acp_messages_db,
    create_sessions_db,
    create_state_vscdb,
)
from devin_internals.parsers import (
    AcpMessage,
    AcpMessagesStore,
    MessageNode,
    PromptHistoryEntry,
    RenderedCommit,
    Session,
    SessionsStore,
    StateVscdbStore,
    SubagentHead,
    ToolCallState,
)

# ---------------------------------------------------------------------------
# sessions.db
# ---------------------------------------------------------------------------


def test_sessions_store_returns_typed_sessions(tmp_path):
    db = create_sessions_db(tmp_path / "sessions.db", n_sessions=4)
    with SessionsStore(db) as store:
        sessions = store.sessions()

    assert len(sessions) == 4
    assert all(isinstance(s, Session) for s in sessions)
    s = sessions[0]
    assert s.id
    assert s.working_directory.startswith("/fixture/workspace/")
    assert s.status in {"active", "hidden"}
    assert isinstance(s.created_at, int)
    # most recently active first
    last = [s.last_activity_at for s in sessions]
    assert last == sorted(last, reverse=True)


def test_sessions_store_limit_and_filter(tmp_path):
    db = create_sessions_db(tmp_path / "sessions.db", n_sessions=4)
    with SessionsStore(db) as store:
        assert len(store.sessions(limit=2)) == 2
        sid = store.sessions()[0].id
        nodes = store.message_nodes(session_id=sid)
        all_nodes = store.message_nodes()

    assert nodes and all(n.session_id == sid for n in nodes)
    assert len(all_nodes) >= len(nodes)
    assert all(isinstance(n, MessageNode) for n in all_nodes)
    roots = [n for n in nodes if n.parent_node_id is None]
    assert len(roots) == 1


def test_sessions_store_remaining_tables(tmp_path):
    db = create_sessions_db(tmp_path / "sessions.db")
    with SessionsStore(db) as store:
        assert all(
            isinstance(t, ToolCallState) for t in store.tool_call_state()
        )
        assert store.tool_call_state()
        assert all(
            isinstance(p, PromptHistoryEntry)
            for p in store.prompt_history()
        )
        assert store.prompt_history()
        assert all(
            isinstance(r, RenderedCommit) for r in store.rendered_commits()
        )
        assert store.rendered_commits()
        assert all(
            isinstance(s, SubagentHead) for s in store.subagent_heads()
        )
        assert store.subagent_heads()
        assert store.app_state()["schema_compat_version"] == "17"
        counts = store.counts()

    assert set(counts) == {
        "sessions",
        "message_nodes",
        "tool_call_state",
        "prompt_history",
        "rendered_commits",
        "subagent_heads",
        "app_state",
        "refinery_schema_history",
    }
    assert all(v > 0 for v in counts.values())


def test_sessions_store_unknown_version_fails_loud(tmp_path):
    db = create_sessions_db(tmp_path / "sessions.db", schema_version=99)
    with pytest.raises(UnknownSchemaVersionError, match="version 99"):
        SessionsStore(db)


def test_sessions_store_unsupported_version_fails(tmp_path):
    db = create_sessions_db(tmp_path / "sessions.db", schema_version=10)
    with pytest.raises(SchemaError, match="unsupported"):
        SessionsStore(db)


def test_sessions_store_rejects_non_sessions_db(tmp_path):
    db = create_acp_messages_db(tmp_path / "acp.db")
    with pytest.raises(SchemaDetectionError):
        SessionsStore(db)


# ---------------------------------------------------------------------------
# acp-messages
# ---------------------------------------------------------------------------


def test_acp_messages_store(tmp_path):
    db = create_acp_messages_db(tmp_path / "acp.db")
    with AcpMessagesStore(db) as store:
        meta = store.meta()
        messages = store.messages()
        counts = store.counts()

    assert meta["fixture.session_id"]
    assert messages and all(isinstance(m, AcpMessage) for m in messages)
    assert [m.position for m in messages] == sorted(
        m.position for m in messages
    )
    assert counts == {"messages": len(messages), "meta": len(meta)}


def test_acp_messages_rejects_wrong_db(tmp_path):
    db = create_sessions_db(tmp_path / "sessions.db")
    with pytest.raises(SchemaDetectionError, match="missing table"):
        AcpMessagesStore(db)


# ---------------------------------------------------------------------------
# state.vscdb
# ---------------------------------------------------------------------------


def test_state_vscdb_store(tmp_path):
    db = create_state_vscdb(tmp_path / "state.vscdb")
    with StateVscdbStore(db) as store:
        keys = store.keys()
        windsurf = store.list_prefix("windsurfSpace.")
        default_prefix = store.list_prefix()
        assert store.get("windsurfSpace.fixture.workspaceId") is not None
        assert store.get("does.not.exist") is None
        counts = store.counts()

    assert len(keys) == counts["ItemTable"]
    assert all(k.startswith("windsurfSpace.") for k in windsurf)
    assert windsurf == default_prefix  # default prefix is windsurfSpace.
    assert "fixture.unrelated.key" in keys
    assert "fixture.unrelated.key" not in windsurf


def test_state_vscdb_rejects_wrong_db(tmp_path):
    db = create_acp_messages_db(tmp_path / "acp.db")
    with pytest.raises(SchemaDetectionError, match="missing table"):
        StateVscdbStore(db)


# ---------------------------------------------------------------------------
# read-only guarantee
# ---------------------------------------------------------------------------


def test_parsers_do_not_modify_dbs(tmp_path):
    sdb = create_sessions_db(tmp_path / "sessions.db")
    adb = create_acp_messages_db(tmp_path / "acp.db")
    vdb = create_state_vscdb(tmp_path / "state.vscdb")
    before = {p: p.read_bytes() for p in (sdb, adb, vdb)}

    with SessionsStore(sdb) as s:
        s.sessions()
        s.counts()
    with AcpMessagesStore(adb) as a:
        a.meta()
        a.messages()
    with StateVscdbStore(vdb) as v:
        v.keys()
        v.list_prefix()

    for p, blob in before.items():
        assert p.read_bytes() == blob
    assert not list(tmp_path.glob("*.db-wal"))
    assert not list(tmp_path.glob("*.db-shm"))
