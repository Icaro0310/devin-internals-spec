"""Version-detector tests: v17 detected, unknown versions fail loudly."""

from __future__ import annotations

import sqlite3

import pytest

from devin_internals import (
    SchemaDetectionError,
    UnknownSchemaVersionError,
    detect_schema_version,
)
from devin_internals.fixtures import create_acp_messages_db, create_sessions_db


def test_detects_v17(tmp_path):
    db = create_sessions_db(tmp_path / "sessions.db")

    info = detect_schema_version(db)

    assert info["schema_version"] == 17
    assert info["schema_compat_version"] == 17
    assert info["known"] is True
    assert info["supported"] is True
    assert info["verified"] is True
    assert info["min_supported"] == 15
    assert info["max_supported"] == 17


def test_accepts_str_path_and_tilde(tmp_path):
    db = create_sessions_db(tmp_path / "sessions.db")
    info = detect_schema_version(str(db))
    assert info["schema_version"] == 17


def test_unknown_version_fails_loudly(tmp_path):
    db = create_sessions_db(tmp_path / "sessions.db", schema_version=99)

    with pytest.raises(UnknownSchemaVersionError, match="version 99"):
        detect_schema_version(db)


def test_old_but_known_version_reports_unsupported(tmp_path):
    db = create_sessions_db(tmp_path / "sessions.db", schema_version=10)

    info = detect_schema_version(db)
    assert info["schema_version"] == 10
    assert info["known"] is True
    assert info["supported"] is False


def test_missing_file_fails(tmp_path):
    with pytest.raises(SchemaDetectionError, match="no such file"):
        detect_schema_version(tmp_path / "nope.db")


def test_wrong_db_fails(tmp_path):
    """A valid SQLite DB without refinery_schema_history is not sessions.db."""
    db = create_acp_messages_db(tmp_path / "acp.db")

    with pytest.raises(SchemaDetectionError, match="refinery_schema_history"):
        detect_schema_version(db)


def test_empty_history_fails(tmp_path):
    db = create_sessions_db(tmp_path / "sessions.db")
    con = sqlite3.connect(db)
    with con:
        con.execute("DELETE FROM refinery_schema_history")
    con.close()

    with pytest.raises(SchemaDetectionError, match="empty"):
        detect_schema_version(db)


def test_detector_does_not_modify_db(tmp_path):
    db = create_sessions_db(tmp_path / "sessions.db")
    before = db.read_bytes()

    detect_schema_version(db)

    assert db.read_bytes() == before
    assert not (tmp_path / "sessions.db-wal").exists()
