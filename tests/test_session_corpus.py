"""Session-corpus tests (docs/SESSION-SURFACES.md §7).

Covers three things: the builders produce the documented physical layouts,
``build_session_corpus`` is byte-deterministic, and ``manifest.json``
validates against its declared shape with warning codes drawn only from the
closed set the spec names.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from devin_internals.fixtures import (
    DEFAULT_SEED,
    create_codex_store,
    create_copilot_session_state,
    create_vscode_chat_storage,
    ms_to_iso,
)
from devin_internals.session_corpus import (
    ALLOWED_WARNING_CODES,
    build_session_corpus,
    main,
)

# The closed set SESSION-SURFACES §4/§5/§6 names — the test pins it so a
# typo'd code can't silently widen the contract.
SPEC_WARNING_CODES = {
    "unknown-workspace",
    "cross-workspace-duplicate",
    "duplicates",
    "session-open",
    "no-end-marker",
    "partial-parse",
    "truncated-tail",
}

RESULT_STATES = {
    "ok",
    "partial",
    "no-sessions",
    "source-not-found",
    "unsupported-format",
    "read-error",
}


# ---------------------------------------------------------------------------
# Layout tests — files exist in the documented shapes
# ---------------------------------------------------------------------------


def _events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_copilot_layouts_cover_all_three(tmp_path):
    out = create_copilot_session_state(tmp_path / "copilot")
    root = out["root"]

    # primary: session-state/<uuid>/{events.jsonl,workspace.yaml}
    dirs = sorted(p for p in (root / "session-state").iterdir() if p.is_dir())
    assert len(dirs) == 2
    for d in dirs:
        assert (d / "events.jsonl").is_file()
        assert (d / "workspace.yaml").is_file()
    # flat: session-state/<uuid>.jsonl
    flats = [p for p in (root / "session-state").iterdir() if p.suffix == ".jsonl"]
    assert len(flats) == 1
    # legacy: history-session-state/<uuid>/events.jsonl
    legacy = list((root / "history-session-state").iterdir())
    assert len(legacy) == 1 and (legacy[0] / "events.jsonl").is_file()
    assert (legacy[0] / "workspace.yaml").is_file()

    by_key = {s["key"]: s for s in out["sessions"]}
    assert by_key["alpha"]["closed_ms"] is not None  # explicit session.shutdown
    assert by_key["beta"]["closed_ms"] is None  # no close marker → inferred
    assert by_key["gamma"]["workspace_seed"] is None  # flat → no workspace.yaml

    # envelope contract §6.3: {id, parentId, timestamp, type, data}
    for s in out["sessions"]:
        for ev in _events(s["events_path"]):
            assert {"id", "parentId", "timestamp", "type", "data"} <= set(ev)
        types = {ev["type"] for ev in _events(s["events_path"])}
        assert "session.start" in types
    git_roots = [
        (d / "workspace.yaml").read_text() for d in dirs
    ] + [(legacy[0] / "workspace.yaml").read_text()]
    assert all("git_root: /fixture/workspace/" in y for y in git_roots)


def test_codex_store_layout(tmp_path):
    out = create_codex_store(tmp_path / "codex")
    root = out["root"]

    assert (root / "state_4.sqlite").is_file()
    con = sqlite3.connect(root / "state_4.sqlite")
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(threads)")}
        assert cols == {"id", "created_at", "updated_at", "cwd", "has_user_event"}
        rows = con.execute(
            "SELECT id, created_at, updated_at, cwd, has_user_event FROM threads"
        ).fetchall()
    finally:
        con.close()
    assert len(rows) == 2
    assert all(r[2] > r[1] for r in rows)  # updated after created
    assert all(r[3].startswith("/fixture/workspace/") for r in rows)

    rollouts = sorted((root / "sessions").glob("rollout-*.jsonl"))
    assert len(rollouts) == 6
    fork = _events(root / "sessions" / "rollout-forked.jsonl")
    assert fork[0]["type"] == "session_meta"
    assert fork[0]["payload"].get("forked_from_id")

    open_recs = _events(root / "sessions" / "rollout-open.jsonl")
    kinds = [r["payload"]["type"] for r in open_recs if r["type"] == "event_msg"]
    assert kinds == ["task_started"]  # started, never completed → session-open

    closed = _events(root / "sessions" / "rollout-closed.jsonl")
    kinds = [r["payload"]["type"] for r in closed if r["type"] == "event_msg"]
    assert kinds == ["task_started", "task_complete"]

    # evidence fixtures (SESSION-EVIDENCE §8): exec-claim pairs a function_call
    # with its output by call_id; bare-claim has no call records at all
    exec_recs = _events(root / "sessions" / "rollout-exec-claim.jsonl")
    items = [r["payload"] for r in exec_recs if r["type"] == "response_item"]
    call = next(i for i in items if i["type"] == "function_call")
    out = next(i for i in items if i["type"] == "function_call_output")
    assert call["call_id"] == out["call_id"]
    assert out["output"]["exit_code"] == 0
    bare_recs = _events(root / "sessions" / "rollout-bare-claim.jsonl")
    assert [r for r in bare_recs if r["type"] == "response_item"
            and r["payload"].get("type") == "function_call"] == []


def _replay_mutation_log(lines: list[str]) -> dict:
    """Replay kinds 0–3 like the reference parser (malformed lines skipped)."""
    doc: dict = {}

    def parent(keys):
        cur = doc
        for p in keys:
            cur = cur.setdefault(p, {})
        return cur

    for line in lines:
        rec = json.loads(line)
        k = rec.get("k", [])
        if rec["kind"] == 0:
            doc = rec["v"]
        elif rec["kind"] == 1:
            if not k:
                doc = rec["v"]
                continue
            parent(k[:-1])[k[-1]] = rec["v"]
        elif rec["kind"] == 2:
            p = parent(k[:-1])
            arr = p.setdefault(k[-1], [])
            items = rec["v"] if isinstance(rec["v"], list) else [rec["v"]]
            if isinstance(rec.get("i"), int):
                arr[rec["i"]:] = items
            else:
                arr.extend(items)
        elif rec["kind"] == 3:
            parent(k[:-1]).pop(k[-1], None)
    return doc


def test_vscode_layout_and_mutation_replay(tmp_path):
    out = create_vscode_chat_storage(tmp_path / "vscode-chat")
    user = out["root"] / "Code" / "User"

    # workspace sessions live under <wsDir>/chatSessions/
    ws_dirs = sorted((user / "workspaceStorage").iterdir())
    assert len(ws_dirs) == 2
    snapshots = list(ws_dirs[0].glob("chatSessions/*.json")) + list(
        ws_dirs[1].glob("chatSessions/*.json")
    )
    logs = list(ws_dirs[0].glob("chatSessions/*.jsonl")) + list(
        ws_dirs[1].glob("chatSessions/*.jsonl")
    )
    assert len(snapshots) == 1 and len(logs) == 1

    snap = json.loads(snapshots[0].read_text())
    assert snap["requests"] and "creationDate" in snap and "version" in snap

    lines = logs[0].read_text().splitlines()
    doc = _replay_mutation_log(lines[:-1])
    assert len(doc["requests"]) == 2
    assert "creationDate" in doc and "lastMessageDate" in doc
    assert "draftState" not in doc  # kind 3 delete applied
    assert doc["requesterUsername"] == "fixture-user"  # kind 1 set applied
    with pytest.raises(json.JSONDecodeError):
        json.loads(lines[-1])  # trailing malformed line → truncated-tail

    global_dir = user / "globalStorage" / "emptyWindowChatSessions"
    globals_ = list(global_dir.glob("*.json"))
    assert len(globals_) == 1
    doc = json.loads(globals_[0].read_text())
    assert "requests" in doc


# ---------------------------------------------------------------------------
# Corpus + manifest tests
# ---------------------------------------------------------------------------


def _file_listing(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_corpus_is_deterministic(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    build_session_corpus(a)
    build_session_corpus(b)
    fa, fb = _file_listing(a), _file_listing(b)
    assert fa.keys() == fb.keys()
    assert fa == fb


def test_manifest_shape(tmp_path):
    root = tmp_path / "corpus"
    manifest_path = build_session_corpus(root)
    m = json.loads(manifest_path.read_text())

    assert m["version"] == 1
    surfaces = [f["surface"] for f in m["fixtures"]]
    assert surfaces == ["copilot-cli", "codex-cli", "vscode-chat"]

    for fixture in m["fixtures"]:
        assert (root / fixture["store_path"]).is_dir()
        for code in fixture["source_warnings"]:
            assert code in ALLOWED_WARNING_CODES
        for s in fixture["sessions"]:
            assert isinstance(s["native_id"], str) and s["native_id"]
            assert s["workspace_seed"] is None or isinstance(s["workspace_seed"], str)
            e = s["expect"]
            assert isinstance(e["id_present"], bool)
            assert e["state"] in RESULT_STATES
            assert set(e["warning_codes"]) <= ALLOWED_WARNING_CODES
            assert e["event_count"] is None or isinstance(e["event_count"], int)
            assert isinstance(e["started_at"], str)
            assert e["ended_at"] is None or isinstance(e["ended_at"], str)

    # §8 non-scope: no content ever reaches the manifest
    blob = manifest_path.read_text()
    assert "xyzzy" not in blob and '"title"' not in blob


def test_manifest_matches_artifacts(tmp_path):
    """Re-derive the mechanical fields from the generated files themselves."""
    root = tmp_path / "corpus"
    m = json.loads(build_session_corpus(root).read_text())
    fixtures_by_surface = {f["surface"]: f for f in m["fixtures"]}

    copilot = {s["native_id"]: s for s in fixtures_by_surface["copilot-cli"]["sessions"]}
    for s in copilot.values():
        events_file = next(
            (root / "copilot").rglob(f"{s['native_id']}*"), None
        )
        assert events_file is not None
        events = _events(
            events_file / "events.jsonl" if events_file.is_dir() else events_file
        )
        assert s["expect"]["started_at"] == events[0]["timestamp"]
        assert s["expect"]["event_count"] == len(events)
        shutdowns = [e for e in events if e["type"] == "session.shutdown"]
        if "session-open" in s["expect"]["warning_codes"]:
            assert s["expect"]["ended_at"] is None
        elif shutdowns:
            assert s["expect"]["ended_at"] == shutdowns[-1]["timestamp"]
        elif s["expect"]["ended_at"] is not None:
            assert s["expect"]["ended_at"] == events[-1]["timestamp"]
            assert "no-end-marker" in s["expect"]["warning_codes"]

    codex = {s["native_id"]: s for s in fixtures_by_surface["codex-cli"]["sessions"]}
    con = sqlite3.connect(root / "codex" / "state_4.sqlite")
    try:
        for tid, created, updated, _cwd, _hue in con.execute(
            "SELECT id, created_at, updated_at, cwd, has_user_event FROM threads"
        ):
            e = codex[tid]["expect"]
            assert e["started_at"] == ms_to_iso(created)
            assert e["ended_at"] == ms_to_iso(updated)
            assert e["warning_codes"] == ["no-end-marker"]
    finally:
        con.close()
    # the forked rollout must have no manifest entry (§6.4 ignores forks)
    fork = _events(root / "codex" / "sessions" / "rollout-forked.jsonl")
    fork_id = fork[0]["payload"]["id"]
    assert fork_id not in codex
    assert fixtures_by_surface["codex-cli"]["source_warnings"] == ["duplicates"]

    vscode = {s["native_id"]: s for s in fixtures_by_surface["vscode-chat"]["sessions"]}
    assert len(vscode) == 3
    by_seed = {s["workspace_seed"]: s for s in vscode.values()}
    assert by_seed[None]["expect"]["id_present"] is False
    # global session is a legitimate identity — never unknown-workspace
    assert by_seed[None]["expect"]["warning_codes"] == []


def test_cli_entrypoint(tmp_path, capsys):
    out = tmp_path / "corpus"
    assert main([str(out)]) == 0
    printed = capsys.readouterr().out.strip()
    assert printed == str(out / "manifest.json")
    assert Path(printed).is_file()


def test_regeneration_cleans_stale_files(tmp_path):
    out = tmp_path / "corpus"
    build_session_corpus(out)
    stale = out / "copilot" / "stale-marker.txt"
    stale.write_text("stale")
    build_session_corpus(out)
    assert not stale.exists()


def test_default_seed_is_used(tmp_path):
    """Corpus pins DEFAULT_SEED so vendored bytes are stable across repos."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    build_session_corpus(a, seed=DEFAULT_SEED)
    build_session_corpus(b)
    assert (a / "manifest.json").read_bytes() == (b / "manifest.json").read_bytes()


def _scanned_copilot_ids(root: Path) -> set[str]:
    """The session set a reader discovers under a copilot root (§6.3)."""
    ids: set[str] = set()
    for state_dir in ("session-state", "history-session-state"):
        d = root / state_dir
        if not d.is_dir():
            continue
        for p in d.iterdir():
            if p.is_dir() and (p / "events.jsonl").is_file():
                ids.add(p.name)
            elif p.is_file() and p.suffix == ".jsonl":
                ids.add(p.stem)
    return ids


def _scanned_vscode_ids(root: Path) -> set[str]:
    """The session set a reader discovers under a VS Code User dir (§6.5):
    only workspaceStorage/*/chatSessions and the two global session dirs —
    never other files that legitimately live under User/."""
    user = root / "Code" / "User"
    ids: set[str] = set()
    storage = user / "workspaceStorage"
    if storage.is_dir():
        for ws_dir in storage.iterdir():
            chat = ws_dir / "chatSessions"
            if chat.is_dir():
                ids.update(
                    p.stem
                    for p in chat.iterdir()
                    if p.is_file() and p.suffix in {".json", ".jsonl"}
                )
    for name in ("emptyWindowChatSessions", "transferredChatSessions"):
        d = user / "globalStorage" / name
        if d.is_dir():
            ids.update(
                p.stem
                for p in d.iterdir()
                if p.is_file() and p.suffix in {".json", ".jsonl"}
            )
    return ids


def test_reseeding_clears_orphan_sessions(tmp_path):
    """A second build at the same root must not retain first-seed sessions —
    a reader scanning the store would see sessions the builder never
    declared. Cleanup is surgical: non-session files planted beside the
    stores must survive the rebuild."""
    cop = tmp_path / "copilot"
    create_copilot_session_state(cop, seed=DEFAULT_SEED)
    stray = cop / "stray-note.txt"  # not a session store — must survive
    stray.write_text("keep me")
    out = create_copilot_session_state(cop, seed=DEFAULT_SEED + 1)
    declared = {s["native_id"] for s in out["sessions"]}
    assert len(declared) == 4
    assert _scanned_copilot_ids(cop) == declared
    assert stray.read_text() == "keep me"

    vs = tmp_path / "vscode"
    create_vscode_chat_storage(vs, seed=DEFAULT_SEED)
    settings = vs / "Code" / "User" / "settings.json"
    other_ws = vs / "Code" / "User" / "workspaceStorage" / "deadbeef" / "state.vscdb"
    for sentinel in (settings, other_ws):
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.write_text("keep me")
    out = create_vscode_chat_storage(vs, seed=DEFAULT_SEED + 1)
    declared = {s["native_id"] for s in out["sessions"]}
    assert len(declared) == 3
    assert _scanned_vscode_ids(vs) == declared
    assert settings.read_text() == "keep me"
    # a wsDir holding non-session content survives intact
    assert other_ws.read_text() == "keep me"

    cdx = tmp_path / "codex"
    create_codex_store(cdx, seed=DEFAULT_SEED)
    stray = cdx / "config.toml"
    stray.write_text("keep me")
    stale_db = cdx / "state_2.sqlite"  # older-N state db — still a session store
    stale_db.write_bytes(b"stale")
    create_codex_store(cdx, seed=DEFAULT_SEED + 1)
    assert {p.name for p in (cdx / "sessions").glob("*.jsonl")} == {
        "rollout-closed.jsonl",
        "rollout-open.jsonl",
        "rollout-forked.jsonl",
        "rollout-duplicate.jsonl",
        "rollout-exec-claim.jsonl",
        "rollout-bare-claim.jsonl",
    }
    assert stray.read_text() == "keep me"
    assert not stale_db.exists()  # state_*.sqlite orphans are removed too


def _logical_dump(db_path: Path) -> str:
    """SQLite content dump — used instead of bytes for *.sqlite files: the
    DB header embeds the writer's SQLITE_VERSION_NUMBER, so cross-platform
    byte equality isn't guaranteed even when the content is identical."""
    con = sqlite3.connect(db_path)
    try:
        return "\n".join(con.iterdump())
    finally:
        con.close()


def test_committed_corpus_matches_generator(tmp_path):
    """The vendored fixtures/session-corpus/ must be identical to a fresh
    build — committing the artifacts without this check lets them silently
    drift from the generator. Text artifacts compare byte-for-byte (writers
    emit LF bytes on every platform); *.sqlite compares by logical dump."""
    committed = Path(__file__).resolve().parents[1] / "fixtures" / "session-corpus"
    build_session_corpus(tmp_path / "corpus")
    fresh = _file_listing(tmp_path / "corpus")
    vendored = _file_listing(committed)
    assert fresh.keys() == vendored.keys()
    for name in fresh:
        if name.endswith(".sqlite"):
            assert _logical_dump(committed / name) == _logical_dump(
                tmp_path / "corpus" / name
            ), name
        else:
            # Generator output is LF-canonical by construction — the fresh
            # side compares byte-exact (an LF violation there IS drift).
            # Only the vendored side may legitimately carry CRLF (a
            # core.autocrlf=true checkout), so normalize it alone.
            assert fresh[name] == vendored[name].replace(b"\r\n", b"\n"), name


# ---------------------------------------------------------------------------
# Evidence manifest tests (docs/SESSION-EVIDENCE.md §8)
# ---------------------------------------------------------------------------

EVIDENCE_CLAIM_KINDS = {"tests", "commit", "file", "push", "http", "url"}
EVIDENCE_VERDICTS = {"verified", "unverified", "no-evidence"}
EVIDENCE_ROLES = {"user", "assistant", "tool", "system"}
EVIDENCE_TOOL_KINDS = {"execute", "write", "other", "unknown"}


def test_evidence_manifest_shape(tmp_path):
    root = tmp_path / "corpus"
    manifest_path = build_session_corpus(root)
    em = json.loads((root / "evidence-manifest.json").read_text())

    assert em["version"] == 1
    manifest = json.loads(manifest_path.read_text())
    declared = {
        (f["surface"], s["native_id"])
        for f in manifest["fixtures"]
        for s in f["sessions"]
    }
    evidence = [(s["surface"], s["native_id"]) for s in em["sessions"]]
    # every corpus session gets exactly one evidence entry — all-empty
    # expectations are still declared, never omitted
    assert set(evidence) == declared and len(evidence) == len(declared)

    for s in em["sessions"]:
        assert s["surface"] in {"copilot-cli", "codex-cli", "vscode-chat"}
        for c in s["expected_claims"]:
            assert c["kind"] in EVIDENCE_CLAIM_KINDS
            assert c["verdict"] in EVIDENCE_VERDICTS
        assert set(s["expected_tool_call_kinds"]) <= EVIDENCE_TOOL_KINDS
        assert set(s["expected_message_roles"]) <= EVIDENCE_ROLES

    # Same §8 non-scope as manifest.json: the evidence manifest asserts
    # vocabulary-level facts, never fixture content — no claim text,
    # commands or workspace paths may leak into it.
    blob = (root / "evidence-manifest.json").read_text()
    for forbidden in ("xyzzy", "pytest", "git push", "/fixture/workspace"):
        assert forbidden not in blob


def _codex_rollout_records(root: Path, native_id: str) -> list[dict]:
    """The rollout file whose session_meta carries ``native_id``, if one
    exists (thread rows have none; the fork/duplicate files are skipped
    by §6.4 but would still match a thread id, so the caller only uses
    this for sessions the manifest binds to the rollout leg)."""
    for f in sorted((root / "codex" / "sessions").glob("rollout-*.jsonl")):
        recs = _events(f)
        if (
            recs
            and recs[0].get("type") == "session_meta"
            and recs[0]["payload"].get("id") == native_id
        ):
            return recs
    return []


def test_evidence_manifest_matches_artifacts(tmp_path):
    """Re-derive the declared evidence from the generated stores — the
    hand-written expectations must match what the bytes actually contain."""
    root = tmp_path / "corpus"
    build_session_corpus(root)
    em = json.loads((root / "evidence-manifest.json").read_text())

    # copilot: *.message types → roles; a tool.execution_* pair → execute
    for s in [s for s in em["sessions"] if s["surface"] == "copilot-cli"]:
        events_file = next((root / "copilot").rglob(f"{s['native_id']}*"), None)
        assert events_file is not None
        events = _events(
            events_file / "events.jsonl" if events_file.is_dir() else events_file
        )
        roles = sorted(
            {
                ev["type"].removesuffix(".message")
                for ev in events
                if ev["type"].endswith(".message")
            }
        )
        assert s["expected_message_roles"] == roles
        has_tool_pair = any(ev["type"] == "tool.execution_start" for ev in events)
        assert s["expected_tool_call_kinds"] == (
            ["execute"] if has_tool_pair else []
        )
        claims_text = " ".join(
            ev["data"].get("text", "")
            for ev in events
            if ev["type"] == "assistant.message"
        )
        for c in s["expected_claims"]:
            assert "tests passed" in claims_text
            assert c["verdict"] == "verified" and has_tool_pair

    # codex: response_item records → roles and execute calls
    for s in [s for s in em["sessions"] if s["surface"] == "codex-cli"]:
        recs = _codex_rollout_records(root, s["native_id"])
        items = [r["payload"] for r in recs if r["type"] == "response_item"]
        roles = sorted({i["role"] for i in items if i.get("type") == "message"})
        calls = [i for i in items if i.get("type") == "function_call"]
        assert s["expected_message_roles"] == roles
        assert s["expected_tool_call_kinds"] == (["execute"] if calls else [])
        claims_text = " ".join(
            b.get("text", "") for i in items for b in i.get("content", [])
        )
        for c in s["expected_claims"]:
            assert "tests passed" in claims_text
            if c["verdict"] == "verified":
                assert calls
            elif c["verdict"] == "no-evidence":
                assert not calls

    # vscode: replay the doc, then requests → user roles, response parts →
    # assistant roles + toolInvocation execute calls
    for s in [s for s in em["sessions"] if s["surface"] == "vscode-chat"]:
        session_file = next(
            (root / "vscode-chat").rglob(f"{s['native_id']}.*"), None
        )
        assert session_file is not None
        lines = session_file.read_text().splitlines()
        doc = (
            json.loads(session_file.read_text())
            if session_file.suffix == ".json"
            else _replay_mutation_log(lines[:-1])  # drop the truncated tail
        )
        roles: set[str] = set()
        kinds: set[str] = set()
        claims_text = ""
        for req in doc.get("requests", []):
            roles.add("user")  # every request is a user turn
            for part in req.get("response", []):
                if part.get("kind") == "toolInvocation" or part.get("toolCallId"):
                    kinds.add("execute")
                else:
                    roles.add("assistant")
                    claims_text += json.dumps(part)
        assert s["expected_message_roles"] == sorted(roles)
        assert s["expected_tool_call_kinds"] == sorted(kinds)
        for c in s["expected_claims"]:
            assert "tests passed" in claims_text
            assert c["verdict"] == "verified" and kinds == {"execute"}
