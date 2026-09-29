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
    con = sqlite3.connect(path)
    with con:
        con.executescript(ACP_MESSAGES_DDL)
        con.executemany(
            "INSERT INTO meta(key, value) VALUES (?, ?)",
            [
                ("fixture.session_id", sid),
                ("fixture.created_at", str(_BASE_TS_MS)),
                ("fixture.meta_version", "1"),
            ],
        )
        kinds = ["fixture.user", "fixture.agent", "fixture.tool_call", "fixture.thought"]
        for pos in range(rng.randint(4, 8)):
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
    sessions_db = create_sessions_db(root / "cli" / "sessions.db", seed=seed)
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
