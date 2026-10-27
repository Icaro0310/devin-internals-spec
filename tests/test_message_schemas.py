"""Message-schema corpus tests (docs/SCHEMA.md §2).

The corpus under ``fixtures/message-schemas/`` (packaged as
``devin_internals/corpus/message-schemas/``) is the executable half of
the ACP payload spec: one fixture per (``messages.kind``,
``meta.schema_version``) + the ``meta`` table per version. These tests
pin the fixture contract — every fixture loads and self-validates,
verified fields are asserted loudly, unverified fields are *never*
asserted (only reported as promotion candidates), and a real store that
contradicts a verified claim fails.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest

from devin_internals.fixtures import create_acp_messages_db, create_sessions_db
from devin_internals.message_schemas import (
    CORPUS_NAME,
    FixtureError,
    extract_shape,
    load_corpus,
    load_fixture,
    verify_db,
    verify_payload,
)
from devin_internals.parsers.acp_messages import KNOWN_ACP_SCHEMA_VERSIONS

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_CORPUS = REPO_ROOT / "fixtures" / CORPUS_NAME

LIVE_ACP_DIR = Path.home() / ".config" / "Devin" / "User" / "acp-messages"
INSTALL_STATES = (
    REPO_ROOT / "fixtures" / "install-states" / "devin-chat"
)


@pytest.fixture(scope="module")
def corpus():
    return load_corpus()


def _base_fixture(**over):
    data = {
        "fixture": "message-schema",
        "format_version": 1,
        "store": "User/acp-messages/<session-uuid>.db",
        "table": "messages",
        "kind": "user_message",
        "meta_schema_version": 6,
        "status": "verified",
        "fields": {
            "kind": {"types": ["str"], "presence": "always",
                     "status": "verified"},
        },
    }
    data.update(over)
    return data


def _user_message_payload(**over):
    payload = {
        "kind": "user_message",
        "id": "m1",
        "content": [
            {
                "sessionUpdate": "user_message_chunk",
                "content": {"type": "text", "text": "x"},
                "_meta": {
                    "cognition.ai/clientMessageId": "c1",
                    "cognition.ai/messageSubIndex": 0,
                    "cognition.ai/timestamp": "t",
                },
            }
        ],
    }
    payload.update(over)
    return payload


# ---------------------------------------------------------------------------
# Corpus loading + file conventions
# ---------------------------------------------------------------------------


def test_corpus_loads_every_fixture(corpus):
    # one fixture per (kind, version) — no gaps, no duplicates
    assert len(corpus.message_fixtures) == 12
    kinds = {k for k, _v in corpus.message_fixtures}
    assert kinds == {
        "user_message", "agent_message", "agent_thought",
        "tool_call", "plan", "subagent", "tool_call_update",
    }


def test_corpus_versions_cover_known_schema_versions(corpus):
    # fixture coverage aligns with the parser's accepted store versions
    assert set(corpus.known_versions) == set(KNOWN_ACP_SCHEMA_VERSIONS)


def test_meta_fixture_per_version(corpus):
    for version in corpus.known_versions:
        meta = corpus.meta_for(version)
        assert meta is not None
        assert meta.table == "meta"
        # every meta fixture pins the integer-as-TEXT version marker
        sv = next(f for f in meta.fields if f.path == "schema_version")
        assert sv.verified and str(version) in sv.values


def test_source_and_packaged_corpus_agree(corpus):
    src = load_corpus(SOURCE_CORPUS)
    assert src.manifest == corpus.manifest
    assert src.message_fixtures == corpus.message_fixtures
    assert src.meta_fixtures == corpus.meta_fixtures


def test_fixture_filenames_encode_kind_and_version():
    name_re = re.compile(r"^(?P<kind>[a-z_]+)\.schema-v(?P<v>\d+)\.json$")
    seen = set()
    for path in SOURCE_CORPUS.glob("*.schema-v*.json"):
        m = name_re.match(path.name)
        assert m, f"{path.name} does not follow <kind>.schema-v<N>.json"
        schema = load_fixture(path)
        assert schema.kind == m["kind"]
        assert schema.meta_schema_version == int(m["v"])
        seen.add(path.name)
    # manifest lists every fixture file
    manifest = json.loads((SOURCE_CORPUS / "manifest.json").read_text())
    assert {e["file"] for e in manifest["fixtures"]} == seen


def test_manifest_kind_vocabulary_matches_fixtures(corpus):
    vocab = corpus.manifest["kind_vocabulary"]["verified"]
    for v_s, kinds in vocab.items():
        for kind in kinds:
            assert corpus.fixture_for(kind, int(v_s)) is not None


def test_every_fixture_has_required_fields(corpus):
    for schema in corpus.message_fixtures.values():
        assert schema.provenance
        statuses = {f.status for f in schema.fields}
        assert statuses <= {"verified", "unverified"}
        if schema.verified:
            assert "verified" in statuses
        # every fixture declares its `kind` discriminator when on messages
        kind_field = next(f for f in schema.fields if f.path == "kind")
        assert kind_field.verified or not schema.verified


def test_verified_fields_have_real_provenance(corpus):
    for schema in corpus.message_fixtures.values():
        if schema.verified:
            assert "inspected" in schema.provenance or "live" in schema.provenance


# ---------------------------------------------------------------------------
# load_fixture validation — the format contract
# ---------------------------------------------------------------------------


def test_load_fixture_rejects_bad_envelope():
    with pytest.raises(FixtureError, match="fixture tag"):
        load_fixture(_base_fixture(fixture="nope"))
    with pytest.raises(FixtureError, match="format_version"):
        load_fixture(_base_fixture(format_version=99))
    with pytest.raises(FixtureError, match="required key"):
        load_fixture({"fixture": "message-schema"})


def test_load_fixture_rejects_bad_field_specs():
    base = _base_fixture()
    with pytest.raises(FixtureError, match="unknown spec keys"):
        load_fixture({**base, "fields": {
            "x": {"types": ["str"], "presence": "always",
                  "status": "verified", "bogus": 1}}})
    with pytest.raises(FixtureError, match="types"):
        load_fixture({**base, "fields": {
            "x": {"types": ["integer"], "presence": "always",
                  "status": "verified"}}})
    with pytest.raises(FixtureError, match="presence"):
        load_fixture({**base, "fields": {
            "x": {"types": ["str"], "presence": "maybe",
                  "status": "verified"}}})


def test_load_fixture_rejects_unverified_without_note():
    with pytest.raises(FixtureError, match="note"):
        load_fixture(_base_fixture(fields={
            "x": {"types": ["str"], "presence": "sometimes",
                  "status": "unverified"},
        }))


def test_load_fixture_rejects_closed_unverified_vocab():
    with pytest.raises(FixtureError, match="closed"):
        load_fixture(_base_fixture(fields={
            "x": {"types": ["str"], "presence": "sometimes",
                  "status": "unverified", "closed": True,
                  "note": "doc"},
        }))


def test_load_fixture_rejects_verified_under_unverified():
    with pytest.raises(FixtureError, match="under unverified"):
        load_fixture(_base_fixture(fields={
            "a": {"types": ["dict"], "presence": "always",
                  "status": "unverified", "note": "doc"},
            "a.b": {"types": ["str"], "presence": "always",
                    "status": "verified"},
        }))


def test_load_fixture_rejects_undeclared_ancestors():
    with pytest.raises(FixtureError, match="not declared"):
        load_fixture(_base_fixture(fields={
            "a": {"types": ["dict"], "presence": "always",
                  "status": "verified"},
            "a.b.c": {"types": ["str"], "presence": "always",
                      "status": "verified"},
        }))
    with pytest.raises(FixtureError, match="non-list"):
        load_fixture(_base_fixture(fields={
            "a": {"types": ["dict"], "presence": "always",
                  "status": "verified"},
            "a.b[]": {"types": ["str"], "presence": "always",
                      "status": "verified"},
        }))
    with pytest.raises(FixtureError, match="non-object"):
        load_fixture(_base_fixture(fields={
            "a": {"types": ["str"], "presence": "always",
                  "status": "verified"},
            "a.b": {"types": ["str"], "presence": "always",
                    "status": "verified"},
        }))


def test_load_fixture_rejects_vocab_overlap():
    with pytest.raises(FixtureError, match="disjoint"):
        load_fixture(_base_fixture(fields={
            "x": {"types": ["str"], "presence": "always",
                  "status": "verified",
                  "values": ["a"], "documented_unverified": ["a"]},
        }))


def test_load_fixture_rejects_duplicate_paths():
    # `a.b` and `a["b"]` are the same segments — spelling must not hide dups
    with pytest.raises(FixtureError, match="duplicate"):
        load_fixture(_base_fixture(fields={
            "a": {"types": ["dict"], "presence": "always",
                  "status": "verified"},
            "a.b": {"types": ["str"], "presence": "always",
                    "status": "verified"},
            "a[\"b\"]": {"types": ["str"], "presence": "always",
                         "status": "verified"},
        }))


def test_load_fixture_rejects_store_checks_on_messages():
    with pytest.raises(FixtureError, match="store_checks"):
        load_fixture(_base_fixture(store_checks=["message_count_equals_row_count"]))
    with pytest.raises(FixtureError, match="unknown store_checks"):
        load_fixture(_base_fixture(table="meta", kind="_meta",
                                   store_checks=["nonsense"]))


# ---------------------------------------------------------------------------
# verify_payload semantics
# ---------------------------------------------------------------------------


def test_verify_payload_clean(corpus):
    schema = corpus.fixture_for("user_message", 6)
    findings = verify_payload(schema, _user_message_payload())
    assert findings["contradictions"] == []


def test_verify_payload_missing_verified_field_fails(corpus):
    schema = corpus.fixture_for("user_message", 6)
    payload = _user_message_payload()
    del payload["id"]
    findings = verify_payload(schema, payload)
    assert any("missing required verified field id" in c
               for c in findings["contradictions"])


def test_verify_payload_type_change_fails(corpus):
    schema = corpus.fixture_for("user_message", 6)
    findings = verify_payload(schema, _user_message_payload(id=42))
    assert any("id has type int" in c for c in findings["contradictions"])


def test_verify_payload_closed_vocab_fails(corpus):
    schema = corpus.fixture_for("user_message", 6)
    payload = _user_message_payload()
    payload["kind"] = "not_a_kind"
    findings = verify_payload(schema, payload)
    assert any("outside declared vocabulary" in c
               for c in findings["contradictions"])


def test_verify_payload_array_fields_checked_per_element(corpus):
    schema = corpus.fixture_for("user_message", 6)
    payload = _user_message_payload()
    payload["content"].append({
        "sessionUpdate": "user_message_chunk",
        "content": {"type": "text", "text": "y"},
        # _meta missing — required on every element
    })
    findings = verify_payload(schema, payload)
    assert any("content" in c and "_meta" in c
               for c in findings["contradictions"])


def test_verify_payload_unverified_field_is_promotion_not_contradiction(corpus):
    # userEdits.commands is v1-only evidence — unverified under v6
    schema = corpus.fixture_for("user_message", 6)
    payload = _user_message_payload(
        userEdits={
            "files": [], "reportId": "r", "turnClientMessageId": "t",
            "commands": [{"commandLine": "ls"}],
        },
    )
    findings = verify_payload(schema, payload)
    assert findings["contradictions"] == []
    assert any("commands" in p for p in findings["promotions"])


def test_verify_payload_unverified_field_never_asserted(corpus):
    # even a wildly mistyped unverified field must not contradict —
    # unverified means "documented, unconfirmed", never a promise
    schema = corpus.fixture_for("user_message", 6)
    payload = _user_message_payload(
        userEdits={
            "files": [], "reportId": "r", "turnClientMessageId": "t",
            "commands": {"not": "a list"},
        },
    )
    findings = verify_payload(schema, payload)
    assert findings["contradictions"] == []


def test_verify_payload_undeclared_field_is_note_only(corpus):
    schema = corpus.fixture_for("user_message", 6)
    findings = verify_payload(schema, _user_message_payload(bonus_field=1))
    assert findings["contradictions"] == []
    assert any("bonus_field" in u for u in findings["undeclared_fields"])


def test_verify_payload_open_node_tolerates_new_children(corpus):
    schema = corpus.fixture_for("user_message", 6)
    payload = _user_message_payload()
    payload["content"][0]["_meta"]["cognition.ai/future-key"] = "v"
    findings = verify_payload(schema, payload)
    assert findings["contradictions"] == []
    # cognition.ai/* is open — a new child is expected, not even a note
    assert findings["undeclared_fields"] == []


def test_verify_payload_rejects_non_object_root(corpus):
    schema = corpus.fixture_for("user_message", 6)
    for bad in ('"just a string"', "[1, 2]", "42", "not json at all {"):
        findings = verify_payload(schema, bad)
        assert findings["contradictions"], bad


# ---------------------------------------------------------------------------
# verify_db — store-level verification
# ---------------------------------------------------------------------------


def _mutate(db: Path, sql: str, args: tuple = ()) -> None:
    con = sqlite3.connect(db)
    with con:
        con.execute(sql, args)


def test_verify_db_accepts_synthetic_conforming_store(tmp_path, corpus):
    db = create_acp_messages_db(tmp_path / "acp.db")
    report = verify_db(db, corpus)
    assert report.ok, report.contradictions
    assert report.meta_schema_version == 6
    assert report.rows_checked > 0
    # fixture.* meta markers are tolerated open-space keys, not drift
    assert set(report.extra_meta_keys) == {
        "fixture.created_at", "fixture.session_id"}


@pytest.mark.parametrize("kind", [
    "user_message", "agent_message", "agent_thought", "tool_call"])
def test_verify_db_detects_missing_verified_payload_field(
        tmp_path, corpus, kind):
    db = create_acp_messages_db(tmp_path / "acp.db")
    con = sqlite3.connect(db)
    row = con.execute(
        "SELECT position, payload FROM messages WHERE kind=? LIMIT 1",
        (kind,)).fetchone()
    con.close()
    payload = json.loads(row[1])
    del payload["id"]
    _mutate(db, "UPDATE messages SET payload=? WHERE position=?",
            (json.dumps(payload), row[0]))
    report = verify_db(db, corpus)
    assert not report.ok
    assert any(f"kind={kind}" in c and "field id" in c
               for c in report.contradictions)


def test_verify_db_detects_unknown_kind(tmp_path, corpus):
    db = create_acp_messages_db(tmp_path / "acp.db")
    _mutate(db,
            "INSERT INTO messages(position, kind, payload) "
            "VALUES (999, 'future_kind', '{}')")
    report = verify_db(db, corpus)
    assert not report.ok
    assert "future_kind" in report.unknown_kinds
    assert any("undocumented kind" in c for c in report.contradictions)


def test_verify_db_detects_unknown_schema_version(tmp_path, corpus):
    db = create_acp_messages_db(tmp_path / "acp.db")
    _mutate(db, "UPDATE meta SET value='9' WHERE key='schema_version'")
    report = verify_db(db, corpus)
    assert not report.ok
    assert any("no '_meta' fixture" in c for c in report.contradictions)


def test_verify_db_detects_message_count_lie(tmp_path, corpus):
    db = create_acp_messages_db(tmp_path / "acp.db")
    _mutate(db, "UPDATE meta SET value='12345' WHERE key='message_count'")
    report = verify_db(db, corpus)
    assert not report.ok
    assert any("message_count" in c for c in report.contradictions)


def test_verify_db_detects_position_gap(tmp_path, corpus):
    db = create_acp_messages_db(tmp_path / "acp.db")
    _mutate(db, "DELETE FROM messages WHERE position=1")
    _mutate(db, "UPDATE meta SET value='6' WHERE key='message_count'")
    report = verify_db(db, corpus)
    assert not report.ok
    assert any("position" in c for c in report.contradictions)


def test_verify_db_detects_non_json_payload(tmp_path, corpus):
    db = create_acp_messages_db(tmp_path / "acp.db")
    _mutate(db, "UPDATE messages SET payload='{broken' WHERE position=0")
    report = verify_db(db, corpus)
    assert not report.ok
    assert any("not valid JSON" in c for c in report.contradictions)


def test_verify_db_rejects_wrong_store(tmp_path, corpus):
    db = create_sessions_db(tmp_path / "sessions.db")
    report = verify_db(db, corpus)
    assert not report.ok
    assert any("missing tables" in c for c in report.contradictions)


def test_verify_db_reports_corrupt_file_not_exception(tmp_path, corpus):
    bad = tmp_path / "corrupt.db"
    bad.write_bytes(b"this is not sqlite at all" * 4)
    report = verify_db(bad, corpus)
    assert not report.ok
    assert any("unreadable" in c for c in report.contradictions)


def test_verify_db_max_rows_per_kind_caps_checks(tmp_path, corpus):
    db = create_acp_messages_db(tmp_path / "acp.db")
    full = verify_db(db, corpus)
    capped = verify_db(db, corpus, max_rows_per_kind=1)
    assert capped.rows_checked <= full.rows_checked
    kinds = {k for k, v in corpus.message_fixtures if v == 6}
    assert capped.rows_checked <= len(kinds) + 1


def test_verify_db_readonly(tmp_path, corpus):
    db = create_acp_messages_db(tmp_path / "acp.db")
    before = db.read_bytes()
    verify_db(db, corpus)
    assert db.read_bytes() == before


# ---------------------------------------------------------------------------
# install-states artifacts as real fail-loud evidence
# ---------------------------------------------------------------------------


def _install_db(state: str) -> Path:
    dbs = list(
        (INSTALL_STATES / state).rglob("acp-messages/*.db"))
    assert dbs, f"no acp db under install-states/devin-chat/{state}"
    return dbs[0]


def test_healthy_install_state_verifies_clean(corpus):
    # the generator emits corpus-conforming v6 payloads
    report = verify_db(_install_db("healthy"), corpus)
    assert report.ok, report.contradictions


def test_corrupt_install_state_fails_loud(corpus):
    report = verify_db(_install_db("corrupt-store"), corpus)
    assert not report.ok


def test_schema_unknown_install_state_fails_loud(corpus):
    report = verify_db(_install_db("schema-unknown"), corpus)
    assert not report.ok


def test_zero_rows_install_state_fails_loud(corpus):
    # meta exists but carries no schema_version — the versioned fixture
    # cannot be selected, which must not silently pass
    report = verify_db(_install_db("zero-rows"), corpus)
    assert not report.ok
    assert any("schema_version" in c for c in report.contradictions)


# ---------------------------------------------------------------------------
# Privacy: fixtures must carry shape only
# ---------------------------------------------------------------------------


_VOCAB_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./-]{0,63}$")
_UUIDY_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-")


def _iter_spec_strings(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_spec_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_spec_strings(v)
    elif isinstance(obj, str):
        yield obj


def test_fixtures_carry_no_content_values():
    """No fixture may embed captured payload values — only field names,
    type names, presence marks and discriminator vocabulary."""
    for path in SOURCE_CORPUS.glob("*.schema-v*.json"):
        data = json.loads(path.read_text())
        for fpath, spec in data["fields"].items():
            for key in ("values", "documented_unverified"):
                for v in spec.get(key, []):
                    assert _VOCAB_RE.match(v), (
                        f"{path.name}:{fpath}.{key} value {v!r} is not a "
                        "discriminator token — vocabulary may not carry content")
            # field paths are names only — never ids
            for segment in re.split(r"[.\[\]\"']+", fpath):
                if segment:
                    assert not _UUIDY_RE.search(segment), (
                        f"{path.name}: path {fpath!r} contains an id-like token")


def test_fixtures_have_no_session_data_blobs():
    # provenance strings describe *how* the shape was taken — they must not
    # carry captured titles/text: cap free-text fields sanely
    for path in SOURCE_CORPUS.glob("*.schema-v*.json"):
        data = json.loads(path.read_text())
        for s in _iter_spec_strings(data):
            assert len(s) < 400, f"{path.name}: overlong string {s[:60]!r}"


# ---------------------------------------------------------------------------
# extract_shape — fixture-authoring aid
# ---------------------------------------------------------------------------


def test_extract_shape_reports_paths_types_not_values():
    payloads = [
        {"a": {"b": "x", "c": [1, 2]}},
        {"a": {"b": "y", "c": [3]}},
        {"a": {"b": None, "c": []}},
    ]
    shape = extract_shape(payloads)
    assert shape["a"]["types"] == ["dict"]
    assert shape["a.b"]["types"] == ["str", "null"] or \
        set(shape["a.b"]["types"]) == {"str", "null"}
    assert shape["a.c"]["types"] == ["list"]
    assert shape["a.c[]"]["types"] == ["int"]
    # presence: b in 3/3 parents, elements counted against parent instances
    assert shape["a.b"]["presence_in_parents"] == [3, 3]
    # no value ever reaches the report
    assert "x" not in json.dumps(shape) and '"y"' not in json.dumps(shape)


# ---------------------------------------------------------------------------
# Live stores (best-effort, skipped off-machine)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not LIVE_ACP_DIR.is_dir() or not list(LIVE_ACP_DIR.glob("*.db")),
    reason="no live acp-messages stores on this machine")
def test_live_stores_verify(corpus):
    """The corpus was built from real captures — live stores must agree."""
    reports = [
        verify_db(db, corpus) for db in sorted(LIVE_ACP_DIR.glob("*.db"))
    ]
    failed = [r for r in reports if not r.ok]
    assert not failed, {r.db: r.contradictions for r in failed}
