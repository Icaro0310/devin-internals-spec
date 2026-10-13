"""Cursor tests — storage shape, atomic commit, fail-open, env override.

Hermetic: every test anchors under ``tmp_path`` (explicit ``dir`` or
``DEVIN_CURSOR_DIR``); nothing touches a real ``.devin``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from devin_internals.cursor import CURSOR_DIR_ENV, Cursor


def test_roundtrip(tmp_path: Path) -> None:
    c = Cursor("extract", dir=tmp_path)
    assert c.get("last_rowid", 0) == 0
    c.set("last_rowid", 4120)
    c.set("batch", {"a": 1})
    c.commit()

    assert (tmp_path / "extract-state.json").is_file()
    fresh = Cursor("extract", dir=tmp_path)
    assert fresh.get("last_rowid") == 4120
    assert fresh.get("batch") == {"a": 1}


def test_missing_file_is_empty(tmp_path: Path) -> None:
    c = Cursor("nope", dir=tmp_path)
    assert c.as_dict() == {}


def test_corrupt_file_fails_open(tmp_path: Path) -> None:
    (tmp_path / "bad-state.json").write_text("{not json", encoding="utf-8")
    c = Cursor("bad", dir=tmp_path)
    assert c.as_dict() == {}
    c.set("recovered", True)
    c.commit()
    assert Cursor("bad", dir=tmp_path).get("recovered") is True


def test_non_dict_file_fails_open(tmp_path: Path) -> None:
    (tmp_path / "arr-state.json").write_text("[1,2]", encoding="utf-8")
    assert Cursor("arr", dir=tmp_path).as_dict() == {}


def test_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CURSOR_DIR_ENV, str(tmp_path))
    c = Cursor("envc", environ=dict(os.environ))
    assert c.path == tmp_path / "envc-state.json"


def test_default_dir_is_cwd_devin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(CURSOR_DIR_ENV, raising=False)
    c = Cursor("local", environ={})
    assert c.path == tmp_path / ".devin" / "local-state.json"


def test_commit_is_atomic_and_creates_parent(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "nested"
    c = Cursor("deep", dir=target)
    c.set("v", 1)
    c.commit()
    assert json.loads((target / "deep-state.json").read_text()) == {"v": 1}
    # no *.tmp left behind
    assert not list(target.glob("*.tmp"))


def test_set_without_commit_is_not_durable(tmp_path: Path) -> None:
    c = Cursor("lazy", dir=tmp_path)
    c.set("v", 9)
    assert not (tmp_path / "lazy-state.json").exists()
    assert Cursor("lazy", dir=tmp_path).get("v") is None


@pytest.mark.parametrize("bad", ["", "a/b", ".hidden"])
def test_invalid_names_rejected(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError):
        Cursor(bad, dir=tmp_path)
