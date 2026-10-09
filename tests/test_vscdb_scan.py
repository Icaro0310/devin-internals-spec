"""IS-1: vscdb-scan — shape-only audit, never values."""
import json
import sqlite3
from pathlib import Path

from devin_internals.cli import main
from devin_internals.parsers.state_vscdb import StateVscdbStore
from devin_internals.parsers.vscdb_scan import _shape, scan


def _mkdb(path: Path, items: dict[str, str]) -> Path:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)")
    con.executemany("INSERT INTO ItemTable (key, value) VALUES (?, ?)",
                    [(k, v.encode()) for k, v in items.items()])
    con.commit(); con.close()
    return path


def test_shape_classification():
    assert _shape('{"a":1}')[0] == "json-object"
    assert _shape('[1,2]')[0] == "json-array"
    assert _shape("42")[0] == "number"
    assert _shape("true")[0] == "bool"
    assert _shape("hello")[0] == "string"
    assert _shape("{broken")[0] == "string"
    assert _shape("")[0] == "empty"


def test_scan_flags_and_hides_values(tmp_path):
    db = _mkdb(tmp_path / "s.vscdb", {
        "editor.fontSize": "14",
        "github.auth_token": "REAL_SECRET_VALUE_SHOULD_NEVER_APPEAR",
        "config": '{"theme":"dark","lang":"pt"}',
    })
    with StateVscdbStore(db) as s:
        report = scan(s)
    blob = json.dumps(report)
    assert "REAL_SECRET_VALUE" not in blob  # value never escapes
    assert report["total_keys"] == 3
    flagged = {k["key"]: k["risk_flags"] for k in report["keys"] if "risk_flags" in k}
    assert "github.auth_token" in flagged
    assert "sensitive-key-name" in flagged["github.auth_token"]
    cfg = next(k for k in report["keys"] if k["key"] == "config")
    assert cfg["value_kind"] == "json-object"
    assert sorted(cfg["json_keys"]) == ["lang", "theme"]


def test_scan_jwt_shape(tmp_path):
    jwt = "a" * 12 + "." + "b" * 12 + "." + "c" * 12
    db = _mkdb(tmp_path / "s.vscdb", {"misc": jwt})
    with StateVscdbStore(db) as s:
        report = scan(s)
    k = report["keys"][0]
    assert "looks-like-jwt" in k["risk_flags"]
    assert jwt not in json.dumps(report)


def test_cli_fail_on_flags(tmp_path, capsys):
    db = _mkdb(tmp_path / "s.vscdb", {"ok": "1"})
    assert main(["vscdb-scan", str(db)]) == 0
    db2 = _mkdb(tmp_path / "s2.vscdb", {"api_token": "x"})
    assert main(["vscdb-scan", str(db2), "--fail-on-flags"]) == 1
    capsys.readouterr()
    assert main(["vscdb-scan", str(db2), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["flagged_keys"] == 1
