"""Unified drift contract (F4): one call, every known contract boundary.

Checks, in one pass over a Devin data directory:

- ``sessions.db`` schema version against the supported range
- ``acp-messages/*.db`` meta ``schema_version`` (observed: 6) and the
  declared ``info``/``truncated`` keys
- usage-shape probe — what token/cost signals actually persist locally.
  Verified on a real install (2026-10): ``tool_call_state`` carries **no**
  cost/usage columns; ``message_nodes.metadata`` carries only
  ``num_tokens_preceding`` (context-window tokens, cumulative); per-turn
  cost exists **only** in the live ACP session meta
  (``total_credit_cost``/``total_acu_cost``) and is never written to disk.
- ``state.vscdb`` presence

Every check returns ``ok``/``drift``/``unknown`` — a ``drift`` means the
stored shape differs from what downstream tools assume and they should
fail loudly rather than misread.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from devin_internals.schema import (
    SchemaError,
    detect_schema_version,
)

# Observed on a real install (2026-10): 47 DBs at v6, 2 legacy DBs at v1.
KNOWN_ACP_SCHEMA_VERSIONS = {1, 6}

_EXPECTED_META_KEYS = {"info", "message_count", "schema_version", "truncated"}

# Verified on a real v17 install: tool_call_state has no cost/usage keys and
# message_nodes.metadata carries only these documented keys.
_KNOWN_MN_METADATA_KEYS = {
    "summarized_from",
    "num_tokens_preceding",
    "is_system_prefix",
    "extensions",
}
_COST_HINT_KEYS = ("cost", "usage", "acu", "credit", "price", "billing")


def _ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def _check_sessions_db(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"status": "missing", "path": str(path)}
    try:
        info = detect_schema_version(path)
    except SchemaError as exc:
        return {"status": "drift", "path": str(path), "error": str(exc)}
    return {
        "status": "ok" if info["supported"] else "drift",
        "path": str(path),
        "schema_version": info["schema_version"],
        "supported_range": [info["min_supported"], info["max_supported"]],
    }


def _check_acp_messages(dir_path: Path) -> dict[str, Any]:
    if not dir_path.is_dir():
        return {"status": "missing", "dir": str(dir_path)}
    dbs = sorted(dir_path.glob("*.db"))
    versions: dict[str, int] = {}
    meta_keys: dict[str, int] = {}
    for db in dbs:
        try:
            con = _ro(db)
            for key, value in con.execute("SELECT key, value FROM meta"):
                meta_keys[key] = meta_keys.get(key, 0) + 1
                if key == "schema_version":
                    try:
                        v = int(value)
                    except (TypeError, ValueError):
                        v = value
                    versions[v] = versions.get(v, 0) + 1
            con.close()
        except sqlite3.Error:
            continue
    unknown_versions = sorted(set(versions) - KNOWN_ACP_SCHEMA_VERSIONS,
                              key=str)
    # ``fixture.*`` keys are the declared self-identification marker of
    # synthetic stores — expected, not drift.
    unexpected_meta = sorted(
        k for k in meta_keys
        if k not in _EXPECTED_META_KEYS and not k.startswith("fixture.")
    )
    status = "ok"
    if unknown_versions or unexpected_meta:
        status = "drift"
    if not dbs:
        status = "missing"
    return {
        "status": status,
        "dir": str(dir_path),
        "db_count": len(dbs),
        "schema_versions": {str(k): v for k, v in versions.items()},
        "unknown_schema_versions": unknown_versions,
        "unexpected_meta_keys": unexpected_meta,
    }


def _cost_keys_in(obj: Any, out: set[str]) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            lowered = key.lower()
            if any(h in lowered for h in _COST_HINT_KEYS):
                out.add(key)
            _cost_keys_in(value, out)
    elif isinstance(obj, list):
        for item in obj[:8]:
            _cost_keys_in(item, out)


def _check_usage_shape(sessions_db: Path) -> dict[str, Any]:
    """What token/cost signals actually persist — verified 2026-10 on v17."""
    if not sessions_db.is_file():
        return {"status": "missing"}
    con = _ro(sessions_db)
    try:
        tables = {
            r[0]
            for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        cost_keys: set[str] = set()
        if "tool_call_state" in tables:
            for (tcc,) in con.execute(
                "SELECT tool_call_update_json FROM tool_call_state "
                "WHERE tool_call_update_json IS NOT NULL LIMIT 500"
            ):
                try:
                    _cost_keys_in(json.loads(tcc), cost_keys)
                except (TypeError, json.JSONDecodeError):
                    continue
        metadata_keys: set[str] = set()
        num_tokens = 0
        if "message_nodes" in tables:
            for (md,) in con.execute(
                "SELECT metadata FROM message_nodes "
                "WHERE metadata IS NOT NULL LIMIT 1000"
            ):
                try:
                    keys = set(json.loads(md))
                except (TypeError, json.JSONDecodeError):
                    continue
                metadata_keys |= keys
                if "num_tokens_preceding" in keys:
                    num_tokens += 1
        # "synthetic" is the declared marker written by make-fixture.
        unexpected = sorted(
            metadata_keys - _KNOWN_MN_METADATA_KEYS - {"synthetic"}
        )
        return {
            "status": "drift" if cost_keys or unexpected else "ok",
            "cost_keys_in_tool_calls": sorted(cost_keys),
            "cost_persisted": bool(cost_keys),
            "num_tokens_preceding_rows": num_tokens,
            "unexpected_metadata_keys": unexpected,
            "note": (
                "per-turn cost lives only in the live ACP session meta "
                "(total_credit_cost/total_acu_cost); local stores persist "
                "num_tokens_preceding as the sole token signal"
            ),
        }
    finally:
        con.close()


def _gui_root(data_root: Path) -> Path:
    """Locate the ``User/`` tree.

    Fixture-style layouts keep ``User/`` under the data root; real Linux
    installs split stores across ``~/.local/share/devin/cli/`` (data) and
    ``~/.config/Devin/User/`` (GUI). Windows/macOS keep them under
    ``%APPDATA%``/``~/Library/Application Support``.
    """
    if (data_root / "User").is_dir():
        return data_root
    import os
    import sys

    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", "")) / "Devin"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Devin"
    else:
        base = Path(
            os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
        ) / "Devin"
    return base


def check_contract(devin_data_dir: str | Path) -> dict[str, Any]:
    """Run every contract check and return the unified drift report."""
    root = Path(devin_data_dir).expanduser()
    gui_root = _gui_root(root)
    sessions_db = root / "cli" / "sessions.db"
    checks = {
        "sessions_db": _check_sessions_db(sessions_db),
        "acp_messages": _check_acp_messages(gui_root / "User" / "acp-messages"),
        "usage_shape": _check_usage_shape(sessions_db),
        "state_vscdb": {
            "status": (
                "ok"
                if (gui_root / "User" / "globalStorage" / "state.vscdb").is_file()
                else "missing"
            ),
            "path": str(gui_root / "User" / "globalStorage" / "state.vscdb"),
        },
    }
    worst = "ok"
    if any(c["status"] == "drift" for c in checks.values()):
        worst = "drift"
    elif any(c["status"] == "missing" for c in checks.values()):
        worst = "missing"
    return {
        "root": str(root),
        "gui_root": str(gui_root),
        "status": worst,
        "checks": checks,
    }
