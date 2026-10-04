"""IS-4/IS-5: typed ACP meta, canonical project keys, commit extraction."""

import json
import sqlite3

import pytest

from devin_internals import fixtures
from devin_internals.commits import commit_references, commits_by_session
from devin_internals.parsers import AcpMessagesStore
from devin_internals.projects import (
    canonical_project_key,
    canonical_project_path,
    project_display_name,
)


class _TC:
    def __init__(self, sid, tcid, call=None, update=None):
        self.session_id = sid
        self.tool_call_id = tcid
        self.tool_call_json = call
        self.tool_call_update_json = update


SHA = "88e41436997e9badacafa057969a2bea3a55e48c"
SHA2 = "5001125b0caab19023dc4eb46d4b46684ec41cc7"


def test_sha_in_call_and_update_deduped():
    tc = _TC("s1", "tc1", call=f'{{"cmd": "git show {SHA}"}}',
             update=f'{{"out": "commit {SHA}"}}')
    refs = commit_references([tc])
    assert len(refs) == 1 and refs[0].sha == SHA


def test_commit_url_carries_repo():
    tc = _TC("s1", "tc1",
             update=f'see https://github.com/o/r/commit/{SHA} done')
    refs = commit_references([tc])
    assert len(refs) == 1
    assert refs[0].sha == SHA and refs[0].repo_url == "github.com/o/r"


def test_short_hex_ignored():
    tc = _TC("s1", "tc1", call='{"hash": "abc1234", "n": 5}')
    assert commit_references([tc]) == []


def test_commits_by_session_rollup():
    tcs = [_TC("s1", "a", call=SHA), _TC("s2", "b", update=SHA2)]
    assert commits_by_session(tcs) == {"s1": {SHA}, "s2": {SHA2}}


def test_typed_meta(tmp_path):
    fixtures.create_acp_messages_db(tmp_path / "acp.db")
    db = tmp_path / "acp.db"
    with AcpMessagesStore(db) as store:
        meta = store.typed_meta()
    assert meta.raw and meta.known_schema
    assert meta.schema_version in (1, 6)


def test_typed_meta_real_shape(tmp_path):
    db = tmp_path / "x.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE meta(key TEXT, value TEXT)")
    con.execute("CREATE TABLE messages(position INT, kind TEXT, payload TEXT)")
    con.executemany(
        "INSERT INTO meta VALUES (?, ?)",
        [("schema_version", "6"), ("message_count", "43"),
         ("truncated", "0"),
         ("info", json.dumps({"title": "My session"}))])
    con.commit(); con.close()
    with AcpMessagesStore(db) as store:
        meta = store.typed_meta()
    assert (meta.schema_version, meta.message_count, meta.truncated,
            meta.title) == (6, 43, False, "My session")


@pytest.mark.parametrize("wd,expected", [
    ("/home/u/devin/foo/", "foo"),
    ("/home/u/devin/Foo", "foo"),
    (None, "(no-project)"),
    ("", "(no-project)"),
])
def test_project_key(wd, expected):
    assert canonical_project_key(wd, platform="linux") == expected


def test_windows_path_casefold():
    p = canonical_project_path("C:\\Users\\U\\Devin\\Foo\\", platform="win32")
    assert p == "c:/users/u/devin/foo"
    assert canonical_project_key("C:\\Users\\U\\Devin\\Foo", "win32") == "foo"
    assert project_display_name("C:\\Users\\U\\Devin\\Foo", "win32") == "foo"
