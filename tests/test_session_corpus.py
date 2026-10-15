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
    assert len(rollouts) == 4
    fork = _events(root / "sessions" / "rollout-forked.jsonl")
    assert fork[0]["type"] == "session_meta"
    assert fork[0]["payload"].get("forked_from_id")

    open_recs = _events(root / "sessions" / "rollout-open.jsonl")
    kinds = [r["payload"]["type"] for r in open_recs if r["type"] == "event_msg"]
    assert kinds == ["task_started"]  # started, never completed → session-open

    closed = _events(root / "sessions" / "rollout-closed.jsonl")
    kinds = [r["payload"]["type"] for r in closed if r["type"] == "event_msg"]
    assert kinds == ["task_started", "task_complete"]


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
