"""Deterministic synthetic fixtures that mimic Devin's local stores.

Only the *DDL* is copied from the real stores (inspected read-only via
``sqlite_master``); every row inserted is synthetic. No real session content
is ever reproduced.

All generators are deterministic: given the same ``seed`` they produce
byte-identical databases, so tests can rely on stable output on Windows and
Linux alike.
"""

from __future__ import annotations

import hashlib
import json
import random
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

LATEST_KNOWN_SCHEMA = 17
MIN_SUPPORTED_SCHEMA = 15
DEFAULT_SEED = 0xD317

# Dates the real migrations landed (docs/SPEC.pt-BR.md §1 — public timeline,
# not row content). Versions above 17 get an obviously synthetic date.
_MIGRATION_APPLIED_ON = {
    **{v: "2026-05-06" for v in range(1, 16)},
    16: "2026-07-05",
    17: "2026-09-14",
}
_FUTURE_MIGRATION_DATE = "9999-12-31"

_BASE_TS_MS = 1_780_000_000_000

# ---------------------------------------------------------------------------
# DDL — copied verbatim from the real stores (schema only, verified 2026-09-29)
# ---------------------------------------------------------------------------

SESSIONS_DB_DDL_V17 = """
CREATE TABLE sessions (
  id TEXT PRIMARY KEY,
  working_directory TEXT NOT NULL,
  backend_type TEXT NOT NULL,
  model TEXT NOT NULL,
  agent_mode TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  last_activity_at INTEGER NOT NULL, title TEXT, main_chain_id INTEGER, shell_last_seen_index INTEGER DEFAULT 0, cogs_json TEXT, workspace_dirs TEXT, hidden INTEGER NOT NULL DEFAULT 0, metadata TEXT);
CREATE TABLE message_nodes (
  row_id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  node_id INTEGER NOT NULL,
  parent_node_id INTEGER,
  chat_message TEXT NOT NULL,
  created_at INTEGER NOT NULL, metadata TEXT,
  FOREIGN KEY (session_id) REFERENCES sessions(id),
  UNIQUE(session_id, node_id)
);
CREATE TABLE tool_call_state (
    session_id    TEXT    NOT NULL,
    tool_call_id  TEXT    NOT NULL,
    tool_call_json     TEXT,
    tool_call_update_json TEXT,
    PRIMARY KEY (session_id, tool_call_id),
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);
CREATE TABLE prompt_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  content TEXT NOT NULL,
  timestamp INTEGER NOT NULL,
  session_id TEXT NOT NULL
, is_shell INTEGER NOT NULL DEFAULT 0);
CREATE TABLE rendered_commits (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  sequence_number INTEGER NOT NULL,
  rendered_html TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  FOREIGN KEY (session_id) REFERENCES sessions(id),
  UNIQUE(session_id, sequence_number)
);
CREATE TABLE subagent_heads (
    session_id    TEXT    NOT NULL,
    agent_id      TEXT    NOT NULL,
    chain_node_id INTEGER NOT NULL,
    updated_at    INTEGER NOT NULL,
    PRIMARY KEY (session_id, agent_id),
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);
CREATE TABLE app_state (
    key TEXT PRIMARY KEY NOT NULL,
    value TEXT NOT NULL
);
CREATE TABLE refinery_schema_history(
             version int4 PRIMARY KEY,
             name VARCHAR(255),
             applied_on VARCHAR(255),
             checksum VARCHAR(255));
CREATE INDEX idx_message_nodes_session
  ON message_nodes(session_id);
CREATE INDEX idx_prompt_history_session
  ON prompt_history(session_id);
CREATE INDEX idx_prompt_history_timestamp
  ON prompt_history(timestamp DESC);
CREATE INDEX idx_rendered_commits_session
  ON rendered_commits(session_id, sequence_number);
CREATE INDEX idx_sessions_activity
  ON sessions(last_activity_at DESC);
CREATE INDEX idx_sessions_hidden ON sessions(hidden);
"""

ACP_MESSAGES_DDL = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE messages (position INTEGER PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL);
"""

STATE_VSCDB_DDL = """
CREATE TABLE ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB);
PRAGMA user_version = 1;
"""


def _checksum(seed: int, version: int) -> str:
    return hashlib.sha256(f"fixture:{seed}:{version}".encode()).hexdigest()


def _fake_uuid(seed: int, tag: str) -> str:
    h = hashlib.sha256(f"uuid:{seed}:{tag}".encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-5{h[13:16]}-8{h[17:20]}-{h[20:32]}"


def create_sessions_db(
    path: str | Path,
    *,
    schema_version: int = LATEST_KNOWN_SCHEMA,
    seed: int = DEFAULT_SEED,
    n_sessions: int = 3,
) -> Path:
    """Create a synthetic ``sessions.db`` at ``path``.

    The layout is always the real v17 DDL; ``schema_version`` only controls the
    rows written to ``refinery_schema_history``/``app_state`` (use > 17 to
    exercise the unknown-version path of the detector).
    """
    if schema_version < 1:
        raise ValueError("schema_version must be >= 1")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    rng = random.Random(seed)
    con = sqlite3.connect(path)
    with con:
        con.executescript(SESSIONS_DB_DDL_V17)
        for v in range(1, schema_version + 1):
            con.execute(
                "INSERT INTO refinery_schema_history(version, name, applied_on, checksum)"
                " VALUES (?, ?, ?, ?)",
                (
                    v,
                    f"synthetic_migration_{v:02d}",
                    _MIGRATION_APPLIED_ON.get(v, _FUTURE_MIGRATION_DATE),
                    _checksum(seed, v),
                ),
            )
        con.execute(
            "INSERT INTO app_state(key, value) VALUES (?, ?)",
            ("schema_compat_version", str(schema_version)),
        )
        for i in range(n_sessions):
            _insert_session(con, rng, seed, i)
    con.close()
    return path


def _insert_session(con: sqlite3.Connection, rng: random.Random, seed: int, i: int) -> None:
    sid = _fake_uuid(seed, f"session-{i}")
    created = _BASE_TS_MS + i * 3_600_000
    con.execute(
        "INSERT INTO sessions(id, working_directory, backend_type, model, agent_mode,"
        " created_at, last_activity_at, title, main_chain_id, shell_last_seen_index,"
        " cogs_json, workspace_dirs, hidden, metadata)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            sid,
            f"/fixture/workspace/{i:02d}",
            "fixture-backend",
            "fixture-model",
            "fixture-mode",
            created,
            created + 120_000,
            f"Fixture session {i}",
            1,
            0,
            json.dumps({"synthetic": True}),
            json.dumps([f"/fixture/workspace/{i:02d}"]),
            0,
            json.dumps({"synthetic": True}),
        ),
    )

    n_nodes = rng.randint(4, 7)
    for node_id in range(1, n_nodes + 1):
        parent = None if node_id == 1 else rng.randrange(1, node_id)
        role = "user" if node_id % 2 else "agent"
        con.execute(
            "INSERT INTO message_nodes(session_id, node_id, parent_node_id,"
            " chat_message, created_at, metadata) VALUES (?, ?, ?, ?, ?, ?)",
            (
                sid,
                node_id,
                parent,
                json.dumps(
                    {"synthetic": True, "role": role, "text": f"fixture message {i}.{node_id}"}
                ),
                created + node_id * 10_000,
                json.dumps({"synthetic": True}),
            ),
        )

    for tc in range(2):
        con.execute(
            "INSERT INTO tool_call_state(session_id, tool_call_id, tool_call_json,"
            " tool_call_update_json) VALUES (?, ?, ?, ?)",
            (
                sid,
                f"fixture-tool-call-{i}-{tc}",
                json.dumps({"synthetic": True, "kind": "tool_call", "n": tc}),
                json.dumps({"synthetic": True, "kind": "tool_call_update", "n": tc}),
            ),
        )

    for p in range(2):
        con.execute(
            "INSERT INTO prompt_history(content, timestamp, session_id, is_shell)"
            " VALUES (?, ?, ?, ?)",
            (f"synthetic prompt {i}.{p}", created + p * 5_000, sid, 0),
        )

    con.execute(
        "INSERT INTO rendered_commits(session_id, sequence_number, rendered_html,"
        " created_at) VALUES (?, ?, ?, ?)",
        (sid, 0, "<div>fixture rendered commit</div>", created + 60_000),
    )
    con.execute(
        "INSERT INTO subagent_heads(session_id, agent_id, chain_node_id, updated_at)"
        " VALUES (?, ?, ?, ?)",
        (sid, f"fixture-agent-{i}", 1, created + 90_000),
    )


def create_acp_messages_db(path: str | Path, *, seed: int = DEFAULT_SEED) -> Path:
    """Create a synthetic per-session ``acp-messages/*.db`` at ``path``."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    rng = random.Random(seed)
    sid = _fake_uuid(seed, "acp-session")
    n_messages = rng.randint(4, 8)
    con = sqlite3.connect(path)
    with con:
        con.executescript(ACP_MESSAGES_DDL)
        con.executemany(
            "INSERT INTO meta(key, value) VALUES (?, ?)",
            [
                ("schema_version", "6"),
                ("info", json.dumps(
                    {"title": f"Fixture ACP session {sid[:8]}",
                     "configOptions": [], "availableCommands": [],
                     "synthetic": True})),
                ("message_count", str(n_messages)),
                ("truncated", "0"),
                ("fixture.session_id", sid),
                ("fixture.created_at", str(_BASE_TS_MS)),
            ],
        )
        # Real kind vocabulary observed on live acp-messages DBs:
        # user_message / agent_message / agent_thought / tool_call.
        kinds = ["user_message", "agent_message", "agent_thought", "tool_call"]
        for pos in range(n_messages):
            con.execute(
                "INSERT INTO messages(position, kind, payload) VALUES (?, ?, ?)",
                (
                    pos,
                    kinds[pos % len(kinds)],
                    json.dumps({"synthetic": True, "position": pos}),
                ),
            )
    con.close()
    return path


def create_state_vscdb(path: str | Path, *, seed: int = DEFAULT_SEED) -> Path:
    """Create a synthetic ``state.vscdb`` at ``path``."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    con = sqlite3.connect(path)
    with con:
        con.executescript(STATE_VSCDB_DDL)
        con.executemany(
            "INSERT INTO ItemTable(key, value) VALUES (?, ?)",
            [
                (
                    "windsurfSpace.fixture.workspaceId",
                    json.dumps({"synthetic": True, "id": _fake_uuid(seed, "workspace")}),
                ),
                (
                    "windsurfSpace.fixture.lastSessionId",
                    json.dumps({"synthetic": True, "id": _fake_uuid(seed, "session")}),
                ),
                ("windsurfSpace.fixture.windowState", json.dumps({"synthetic": True})),
                ("fixture.unrelated.key", json.dumps({"synthetic": True})),
            ],
        )
    con.close()
    return path


def create_devin_data_dir(
    root: str | Path,
    *,
    seed: int = DEFAULT_SEED,
    n_acp_dbs: int = 2,
    schema_version: int = LATEST_KNOWN_SCHEMA,
    n_sessions: int = 3,
) -> dict[str, Path | list[Path] | None]:
    """Create a synthetic Devin data directory tree under ``root``.

    Mirrors the real layout::

        <root>/cli/sessions.db
        <root>/User/acp-messages/<uuid>.db        (n_acp_dbs files)
        <root>/User/globalStorage/state.vscdb

    Returns the created paths so callers/tests can locate stores the same way
    ``devin-inspect health`` does.
    """
    root = Path(root)
    sessions_db = create_sessions_db(
        root / "cli" / "sessions.db",
        schema_version=schema_version,
        seed=seed,
        n_sessions=n_sessions,
    )
    acp_dbs = [
        create_acp_messages_db(
            root / "User" / "acp-messages" / f"{_fake_uuid(seed, f'acp-{i}')}.db",
            seed=seed + i,
        )
        for i in range(n_acp_dbs)
    ]
    state_vscdb = create_state_vscdb(
        root / "User" / "globalStorage" / "state.vscdb", seed=seed
    )
    return {
        "root": root,
        "sessions_db": sessions_db,
        "acp_messages": acp_dbs,
        "state_vscdb": state_vscdb,
    }


# ---------------------------------------------------------------------------
# Non-Devin session surfaces (docs/SESSION-SURFACES.md §6.3–§6.5, §7)
#
# Unlike the Devin stores above there is no verbatim DDL to copy: the layouts
# below follow the *documented* file shapes (envelope, record kinds, column
# list) observed by the reference parsers. Every timestamp is a fixed epoch-ms
# offset from _BASE_TS_MS — no wall-clock reads — so generated stores are
# byte-stable and every "last activity" is comfortably stale for the §5
# ended_at inference chain.
# ---------------------------------------------------------------------------

_CORPUS_T0_MS = _BASE_TS_MS  # session-corpus anchor: ~2026-05, always "old"


def ms_to_iso(ms: int) -> str:
    """Epoch milliseconds → ISO 8601 with millisecond precision and ``Z``."""
    return (
        datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _iso_to_ms(iso: str) -> int:
    """Inverse of :func:`ms_to_iso` — the ``Z``-suffixed form only."""
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def _write_jsonl(path: Path, lines: list[str], *, trailing_newline: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines) + ("\n" if trailing_newline else "")
    path.write_text(text, encoding="utf-8")
    return path


def _copilot_event(seq: int, parent: str | None, ts_ms: int, type_: str, data: dict) -> dict:
    """One events.jsonl record — envelope {id, parentId, timestamp, type, data}."""
    return {
        "id": f"evt-{seq:04d}",
        "parentId": parent,
        "timestamp": ms_to_iso(ts_ms),
        "type": type_,
        "data": data,
    }


def _copilot_workspace_yaml(seed_path: str) -> str:
    # workspace.yaml is a flat key: value file; git_root is the preferred
    # workspace seed per §6.3.
    return f"git_root: {seed_path}\ncwd: {seed_path}\n"


def create_copilot_session_state(root: str | Path, *, seed: int = DEFAULT_SEED) -> dict:
    """Create a synthetic copilot-cli root under ``root`` (``~/.copilot`` shape).

    Covers all three layouts in SESSION-SURFACES §6.3:

    - ``session-state/<uuid>/{events.jsonl, workspace.yaml}`` — two sessions:
      ``alpha`` with an explicit ``session.shutdown`` (§5.1 close, no warning)
      and ``beta`` with no close marker and stale timestamps (§5.3 inferred
      close → ``no-end-marker``).
    - ``session-state/<uuid>.jsonl`` — one flat session with a shutdown but no
      workspace.yaml (``unknown-workspace``, id stays null per §4).
    - ``history-session-state/<uuid>/`` — one legacy session, clean close.

    Returns ``{"root", "sessions": [...]}`` with per-session facts (native_id,
    workspace seed, event count, ms timestamps) for manifest generation.
    """
    root = Path(root)
    sessions: list[dict] = []

    def emit(key: str, layout: str, events_dir: Path | None, events_file: Path,
             workspace_seed: str | None, events: list[dict]) -> None:
        _write_jsonl(events_file, [json.dumps(e) for e in events])
        if events_dir is not None and workspace_seed is not None:
            (events_dir / "workspace.yaml").write_text(
                _copilot_workspace_yaml(workspace_seed), encoding="utf-8"
            )
        stamps = [e["timestamp"] for e in events]
        assert stamps == sorted(stamps), f"{key}: events must be time-ordered"
        sessions.append(
            {
                "key": key,
                "native_id": events_file.name.removesuffix(".jsonl")
                if events_dir is None
                else events_dir.name,
                "layout": layout,
                "workspace_seed": workspace_seed,
                "events_path": events_file,
                "started_ms": _iso_to_ms(events[0]["timestamp"]),
                "last_activity_ms": _iso_to_ms(events[-1]["timestamp"]),
                "closed_ms": next(
                    (
                        _iso_to_ms(e["timestamp"])
                        for e in reversed(events)
                        if e["type"] == "session.shutdown"
                    ),
                    None,
                ),
                "event_count": len(events),
            }
        )

    t = _CORPUS_T0_MS
    alpha_id = _fake_uuid(seed, "copilot-alpha")
    emit(
        "alpha",
        "session-state-dir",
        root / "session-state" / alpha_id,
        root / "session-state" / alpha_id / "events.jsonl",
        "/fixture/workspace/alpha",
        [
            _copilot_event(1, None, t, "session.start",
                           {"id": alpha_id, "version": "0.0.0-fixture"}),
            _copilot_event(2, "evt-0001", t + 5_000, "user.message",
                           {"text": "xyzzy copilot marker alpha"}),
            _copilot_event(3, "evt-0002", t + 10_000, "assistant.message",
                           {"text": "xyzzy copilot marker alpha reply"}),
            _copilot_event(4, "evt-0003", t + 20_000, "session.shutdown",
                           {"reason": "fixture-close"}),
        ],
    )
    beta_id = _fake_uuid(seed, "copilot-beta")
    emit(
        "beta",
        "session-state-dir",
        root / "session-state" / beta_id,
        root / "session-state" / beta_id / "events.jsonl",
        "/fixture/workspace/beta",
        [
            _copilot_event(1, None, t + 3_600_000, "session.start",
                           {"id": beta_id, "version": "0.0.0-fixture"}),
            _copilot_event(2, "evt-0001", t + 3_605_000, "user.message",
                           {"text": "xyzzy copilot marker beta"}),
            _copilot_event(3, "evt-0002", t + 3_610_000, "assistant.message",
                           {"text": "xyzzy copilot marker beta reply"}),
        ],
    )
    gamma_id = _fake_uuid(seed, "copilot-gamma")
    emit(
        "gamma",
        "session-state-flat",
        None,
        root / "session-state" / f"{gamma_id}.jsonl",
        None,
        [
            _copilot_event(1, None, t + 7_200_000, "session.start",
                           {"id": gamma_id, "version": "0.0.0-fixture"}),
            _copilot_event(2, "evt-0001", t + 7_205_000, "user.message",
                           {"text": "xyzzy copilot marker gamma"}),
            _copilot_event(3, "evt-0002", t + 7_215_000, "session.shutdown",
                           {"reason": "fixture-close"}),
        ],
    )
    delta_id = _fake_uuid(seed, "copilot-delta")
    emit(
        "delta",
        "history-session-state",
        root / "history-session-state" / delta_id,
        root / "history-session-state" / delta_id / "events.jsonl",
        "/fixture/workspace/legacy",
        [
            _copilot_event(1, None, t + 10_800_000, "session.start",
                           {"id": delta_id, "version": "0.0.0-fixture"}),
            _copilot_event(2, "evt-0001", t + 10_805_000, "user.message",
                           {"text": "xyzzy copilot marker delta"}),
            _copilot_event(3, "evt-0002", t + 10_808_000, "assistant.message",
                           {"text": "xyzzy copilot marker delta reply"}),
            _copilot_event(4, "evt-0003", t + 10_830_000, "session.shutdown",
                           {"reason": "fixture-close"}),
        ],
    )
    return {"root": root, "sessions": sessions}


def _ws_dir_name(seed: int, tag: str) -> str:
    """Deterministic 32-hex workspace dir name — VS Code's stable ws hash."""
    return hashlib.sha256(f"wsdir:{seed}:{tag}".encode()).hexdigest()[:32]


CODEX_THREADS_DDL = """
CREATE TABLE threads (
  id TEXT PRIMARY KEY,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  cwd TEXT NOT NULL,
  has_user_event INTEGER NOT NULL
);
"""


def _rollout_record(ts_ms: int, type_: str, payload: dict) -> str:
    return json.dumps({"timestamp": ms_to_iso(ts_ms), "type": type_, "payload": payload})


def _rollout_meta(native_id: str, cwd: str, ts_ms: int, **extra: str) -> str:
    return _rollout_record(
        ts_ms, "session_meta", {"id": native_id, "cwd": cwd, "timestamp": ms_to_iso(ts_ms), **extra}
    )


def _rollout_task(kind: str, ts_ms: int) -> str:
    return _rollout_record(ts_ms, "event_msg", {"type": kind})


def create_codex_store(root: str | Path, *, seed: int = DEFAULT_SEED) -> dict:
    """Create a synthetic codex-cli home under ``root`` (``~/.codex`` shape).

    SESSION-SURFACES §6.4: ``state_4.sqlite`` wins for its two ``threads``
    rows (``id``, ``created_at``, ``updated_at``, ``cwd``, ``has_user_event`` —
    the exact column list the reference parser selects). Neither thread has a
    close marker, so both are stale-activity inferred closes (§5.3,
    ``no-end-marker``). ``sessions/`` holds four rollout JSONL files:

    - ``rollout-closed``: ``session_meta`` + ``task_started`` + ``task_complete``
      (explicit close, §5.1).
    - ``rollout-open``: ``task_started`` with no matching ``task_complete``
      (``session-open`` per §6.4).
    - ``rollout-forked``: ``forked_from_id`` present — must be ignored.
    - ``rollout-duplicate``: same native id + cwd as thread A — ``duplicates``.

    Returns ``{"root", "state_db", "sessions", "ignored"}`` for manifest use.
    """
    root = Path(root)
    state_db = root / "state_4.sqlite"
    state_db.parent.mkdir(parents=True, exist_ok=True)
    if state_db.exists():
        state_db.unlink()

    t = _CORPUS_T0_MS
    thread_a = _fake_uuid(seed, "codex-thread-a")
    thread_b = _fake_uuid(seed, "codex-thread-b")
    rows = [
        (thread_a, t + 14_400_000, t + 14_520_000, "/fixture/workspace/codex-a", 1),
        (thread_b, t + 18_000_000, t + 18_060_000, "/fixture/workspace/codex-b", 0),
    ]
    con = sqlite3.connect(state_db)
    with con:
        con.executescript(CODEX_THREADS_DDL)
        con.executemany(
            "INSERT INTO threads(id, created_at, updated_at, cwd, has_user_event)"
            " VALUES (?, ?, ?, ?, ?)",
            rows,
        )
    con.close()

    sessions: list[dict] = [
        {
            "key": "thread-a",
            "native_id": thread_a,
            "workspace_seed": "/fixture/workspace/codex-a",
            "started_ms": t + 14_400_000,
            "last_activity_ms": t + 14_520_000,
            "closed_ms": None,
            "event_count": None,
            "source": "state-4",
        },
        {
            "key": "thread-b",
            "native_id": thread_b,
            "workspace_seed": "/fixture/workspace/codex-b",
            "started_ms": t + 18_000_000,
            "last_activity_ms": t + 18_060_000,
            "closed_ms": None,
            "event_count": None,
            "source": "state-4",
        },
    ]

    rollout_c = _fake_uuid(seed, "codex-rollout-c")
    rollout_d = _fake_uuid(seed, "codex-rollout-d")
    files = {
        "rollout-closed.jsonl": [
            _rollout_meta(rollout_c, "/fixture/workspace/codex-c", t + 21_600_000),
            _rollout_task("task_started", t + 21_605_000),
            _rollout_task("task_complete", t + 21_645_000),
        ],
        "rollout-open.jsonl": [
            _rollout_meta(rollout_d, "/fixture/workspace/codex-d", t + 25_200_000),
            _rollout_task("task_started", t + 25_205_000),
        ],
        # Forks are ignored entirely (§6.4): parses fine, carries
        # forked_from_id, never becomes a session.
        "rollout-forked.jsonl": [
            _rollout_meta(
                _fake_uuid(seed, "codex-rollout-e"),
                "/fixture/workspace/codex-c",
                t + 28_800_000,
                forked_from_id=rollout_c,
            ),
            _rollout_task("task_started", t + 28_805_000),
            _rollout_task("task_complete", t + 28_815_000),
        ],
        # Same native id + same workspace as thread A → skipped, `duplicates`.
        "rollout-duplicate.jsonl": [
            _rollout_meta(thread_a, "/fixture/workspace/codex-a", t + 32_400_000),
            _rollout_task("task_started", t + 32_405_000),
            _rollout_task("task_complete", t + 32_430_000),
        ],
    }
    for name, lines in files.items():
        _write_jsonl(root / "sessions" / name, lines)

    sessions += [
        {
            "key": "rollout-closed",
            "native_id": rollout_c,
            "workspace_seed": "/fixture/workspace/codex-c",
            "started_ms": t + 21_600_000,
            "last_activity_ms": t + 21_645_000,
            "closed_ms": t + 21_645_000,
            "event_count": 3,
            "source": "rollout",
        },
        {
            "key": "rollout-open",
            "native_id": rollout_d,
            "workspace_seed": "/fixture/workspace/codex-d",
            "started_ms": t + 25_200_000,
            "last_activity_ms": t + 25_205_000,
            "closed_ms": None,
            "event_count": 2,
            "source": "rollout",
        },
    ]
    return {
        "root": root,
        "state_db": state_db,
        "sessions": sessions,
        "ignored": [
            {"key": "rollout-forked", "reason": "forked_from_id"},
            {"key": "rollout-duplicate", "reason": "duplicates"},
        ],
    }


def create_vscode_chat_storage(root: str | Path, *, seed: int = DEFAULT_SEED) -> dict:
    """Create a synthetic VS Code chat store under ``root`` (config-dir shape).

    SESSION-SURFACES §6.5: ``<root>/Code/User/workspaceStorage/<wsDir>/
    chatSessions/`` holds ``snap-a.json`` (final snapshot) and, under a second
    workspace dir, ``log-b.jsonl`` (mutation log replayed in order — kinds 0–3
    plus one malformed tail line → ``truncated-tail``).
    ``globalStorage/emptyWindowChatSessions/global-c.json`` is a global
    session: ``workspace_hash`` null is a legitimate identity per spec, **not**
    ``unknown-workspace``. All sessions end with a completed last request
    (task-complete-style close, §5.1).
    """
    root = Path(root)
    t = _CORPUS_T0_MS
    variant = root / "Code" / "User"

    snap_id = _fake_uuid(seed, "vscode-snap-a")
    ws_a = _ws_dir_name(seed, "vscode-alpha")
    snap_doc = {
        "version": 3,
        "sessionId": snap_id,
        "requesterUsername": "fixture-user",
        "responderUsername": "fixture-agent",
        "creationDate": t + 36_000_000,
        "lastMessageDate": t + 36_090_000,
        "requests": [
            {"requestId": "req-1", "timestamp": t + 36_010_000,
             "responseTimestamp": t + 36_030_000},
            {"requestId": "req-2", "timestamp": t + 36_060_000,
             "responseTimestamp": t + 36_090_000,
             "result": {"timings": {"totalElapsed": 8000}}},
        ],
    }
    snap_path = variant / "workspaceStorage" / ws_a / "chatSessions" / f"{snap_id}.json"
    snap_path.parent.mkdir(parents=True, exist_ok=True)
    snap_path.write_text(json.dumps(snap_doc, indent=2) + "\n", encoding="utf-8")

    log_id = _fake_uuid(seed, "vscode-log-b")
    ws_b = _ws_dir_name(seed, "vscode-beta")
    base = t + 39_600_000
    log_lines = [
        # kind 0: replace document
        json.dumps({"kind": 0, "k": [], "v": {
            "version": 3,
            "sessionId": log_id,
            "creationDate": base,
            "requests": [],
            "draftState": {"editing": True},
        }}),
        # kind 1: set at path
        json.dumps({"kind": 1, "k": ["requesterUsername"], "v": "fixture-user"}),
        # kind 2: append to array at path
        json.dumps({"kind": 2, "k": ["requests"], "v": {
            "requestId": "req-1", "timestamp": base + 10_000,
            "responseTimestamp": base + 25_000,
        }}),
        json.dumps({"kind": 2, "k": ["requests"], "v": {
            "requestId": "req-2", "timestamp": base + 40_000,
            "result": {"timings": {"totalElapsed": 12000}},
        }}),
        json.dumps({"kind": 1, "k": ["lastMessageDate"], "v": base + 52_000}),
        # kind 3: delete path
        json.dumps({"kind": 3, "k": ["draftState"]}),
        # partially written tail → `truncated-tail` (§6.5)
        '{"kind": 2, "k": ["requests"], "v": {"requestId": "req-3", "timestamp":',
    ]
    log_path = variant / "workspaceStorage" / ws_b / "chatSessions" / f"{log_id}.jsonl"
    _write_jsonl(log_path, log_lines, trailing_newline=False)

    global_id = _fake_uuid(seed, "vscode-global-c")
    gbase = t + 43_200_000
    global_doc = {
        "version": 3,
        "sessionId": global_id,
        "creationDate": gbase,
        "lastMessageDate": gbase + 15_000,
        "requests": [
            {"requestId": "req-1", "timestamp": gbase + 5_000,
             "responseTimestamp": gbase + 15_000},
        ],
    }
    global_path = (
        variant / "globalStorage" / "emptyWindowChatSessions" / f"{global_id}.json"
    )
    global_path.parent.mkdir(parents=True, exist_ok=True)
    global_path.write_text(json.dumps(global_doc, indent=2) + "\n", encoding="utf-8")

    return {
        "root": root,
        "sessions": [
            {
                "key": "snap-a",
                "native_id": snap_id,
                "workspace_seed": ws_a,
                "started_ms": t + 36_000_000,
                "last_activity_ms": t + 36_090_000,
                "closed_ms": t + 36_090_000,
                "event_count": 2,
                "file": snap_path,
            },
            {
                "key": "log-b",
                "native_id": log_id,
                "workspace_seed": ws_b,
                "started_ms": base,
                "last_activity_ms": base + 52_000,
                "closed_ms": base + 52_000,
                "event_count": 2,
                "file": log_path,
            },
            {
                "key": "global-c",
                "native_id": global_id,
                "workspace_seed": None,
                "started_ms": gbase,
                "last_activity_ms": gbase + 15_000,
                "closed_ms": gbase + 15_000,
                "event_count": 1,
                "file": global_path,
            },
        ],
    }
