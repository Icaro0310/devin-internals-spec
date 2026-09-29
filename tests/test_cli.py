"""CLI tests for ``devin-inspect`` (schema / sessions / health)."""

from __future__ import annotations

import json

from devin_internals.cli import main
from devin_internals.fixtures import (
    create_devin_data_dir,
    create_sessions_db,
)


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------


def test_schema_prints_contract(tmp_path, capsys):
    db = create_sessions_db(tmp_path / "sessions.db")
    rc = main(["schema", str(db)])

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["schema_version"] == 17
    assert out["known"] is True
    assert out["min_supported"] == 15
    assert out["max_supported"] == 17


def test_schema_unknown_version_fails_loud(tmp_path, capsys):
    db = create_sessions_db(tmp_path / "sessions.db", schema_version=99)
    rc = main(["schema", str(db)])

    captured = capsys.readouterr()
    assert rc == 1
    assert "version 99" in captured.err
    assert captured.out == ""


# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------


def test_sessions_table_output(tmp_path, capsys):
    db = create_sessions_db(tmp_path / "sessions.db", n_sessions=3)
    rc = main(["sessions", str(db)])

    out = capsys.readouterr().out
    assert rc == 0
    assert "ID" in out and "TITLE" in out and "STATUS" in out
    assert "Fixture session" in out


def test_sessions_json_and_limit(tmp_path, capsys):
    db = create_sessions_db(tmp_path / "sessions.db", n_sessions=4)
    rc = main(["sessions", str(db), "--limit", "2", "--json"])

    rows = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert len(rows) == 2
    for row in rows:
        assert {"id", "title", "working_directory", "created_at", "status"} <= set(
            row
        )


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------


def test_health_on_fixture_tree(tmp_path, capsys):
    create_devin_data_dir(tmp_path / "devin")
    rc = main(["health", str(tmp_path / "devin"), "--json"])

    report = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert report["ok"] is True
    stores = report["stores"]
    assert stores["sessions_db"]["exists"] is True
    assert stores["sessions_db"]["schema_version"] == 17
    assert stores["sessions_db"]["counts"]["sessions"] > 0
    assert stores["acp_messages"]["exists"] is True
    assert stores["acp_messages"]["count"] == 2
    assert all(
        d["counts"]["messages"] > 0 for d in stores["acp_messages"]["dbs"]
    )
    assert stores["state_vscdb"]["exists"] is True
    assert stores["state_vscdb"]["windsurf_keys"] > 0


def test_health_degraded_when_stores_missing(tmp_path, capsys):
    root = tmp_path / "devin"
    create_sessions_db(root / "cli" / "sessions.db")  # no User/ tree
    rc = main(["health", str(root)])

    out = capsys.readouterr().out
    assert rc == 1
    assert "sessions.db" in out and "MISSING" in out
    assert "DEGRADED" in out


def test_health_reports_unknown_schema(tmp_path, capsys):
    root = tmp_path / "devin"
    create_devin_data_dir(root)
    create_sessions_db(root / "cli" / "sessions.db", schema_version=99)

    rc = main(["health", str(root), "--json"])
    report = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert report["ok"] is False
    assert "version 99" in report["stores"]["sessions_db"]["error"]


def test_health_missing_dir(tmp_path, capsys):
    rc = main(["health", str(tmp_path / "nope")])
    assert rc == 1
    capsys.readouterr()
