"""``devin-inspect`` — thin CLI wrapper; all logic lives in the library.

Subcommands (all read-only, all accept ``--json``):

- ``schema <path>``             print the schema-detection contract as JSON
- ``sessions <sessions.db>``    list sessions (id, title, cwd, created_at, status)
- ``health <devin-data-dir>``   locate the three stores, report versions/counts
- ``make-fixture <out>``        write deterministic synthetic stores for tests
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from devin_internals import fixtures
from devin_internals.contract import check_contract
from devin_internals.parsers import (
    AcpMessagesStore,
    SessionsStore,
    StateVscdbStore,
)
from devin_internals.schema import SchemaError, detect_schema_version


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=False))


def _ms_to_iso(ts: int | None) -> str:
    if ts is None:
        return "-"
    return (
        datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _fmt_table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [
        max([len(h), *(len(r[i]) for r in rows)])
        for i, h in enumerate(headers)
    ]
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    sep = "  ".join("-" * widths[i] for i in range(len(headers)))
    body = [
        "  ".join(r[i].ljust(widths[i]) for i in range(len(headers)))
        for r in rows
    ]
    return "\n".join([line, sep, *body])


def _truncate(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


# ---------------------------------------------------------------------------
# subcommands
# ---------------------------------------------------------------------------


def cmd_schema(args: argparse.Namespace) -> int:
    info = detect_schema_version(args.path)
    _print_json(info)
    return 0


def cmd_sessions(args: argparse.Namespace) -> int:
    with SessionsStore(args.path) as store:
        sessions = store.sessions(limit=args.limit)
    if args.json:
        _print_json(
            [
                {**asdict(s), "status": s.status}
                for s in sessions
            ]
        )
        return 0
    rows = [
        [
            _truncate(s.id, 36),
            _truncate(s.title or "-", 30),
            _truncate(s.working_directory, 40),
            _ms_to_iso(s.created_at),
            s.status,
        ]
        for s in sessions
    ]
    if rows:
        print(_fmt_table(["ID", "TITLE", "CWD", "CREATED_AT", "STATUS"], rows))
    else:
        print("no sessions")
    return 0


def _health_sessions_db(path: Path) -> dict[str, Any]:
    entry: dict[str, Any] = {"path": str(path), "exists": path.is_file()}
    if not entry["exists"]:
        return entry
    try:
        info = detect_schema_version(path)
        with SessionsStore(path) as store:
            entry["counts"] = store.counts()
        entry["schema_version"] = info["schema_version"]
        entry["supported"] = info["supported"]
    except SchemaError as exc:
        entry["error"] = str(exc)
    return entry


def _health_acp_messages(dir_path: Path) -> dict[str, Any]:
    entry: dict[str, Any] = {"dir": str(dir_path), "exists": dir_path.is_dir()}
    if not entry["exists"]:
        return entry
    dbs = []
    for db in sorted(dir_path.glob("*.db")):
        item: dict[str, Any] = {"name": db.name, "path": str(db)}
        try:
            with AcpMessagesStore(db) as store:
                item["counts"] = store.counts()
        except SchemaError as exc:
            item["error"] = str(exc)
        dbs.append(item)
    entry["dbs"] = dbs
    entry["count"] = len(dbs)
    return entry


def _health_state_vscdb(path: Path) -> dict[str, Any]:
    entry: dict[str, Any] = {"path": str(path), "exists": path.is_file()}
    if not entry["exists"]:
        return entry
    try:
        with StateVscdbStore(path) as store:
            entry["counts"] = store.counts()
            entry["windsurf_keys"] = len(store.list_prefix())
    except SchemaError as exc:
        entry["error"] = str(exc)
    return entry


def cmd_health(args: argparse.Namespace) -> int:
    root = Path(args.devin_data_dir).expanduser()
    report = {
        "root": str(root),
        "exists": root.is_dir(),
        "stores": {
            "sessions_db": _health_sessions_db(root / "cli" / "sessions.db"),
            "acp_messages": _health_acp_messages(
                root / "User" / "acp-messages"
            ),
            "state_vscdb": _health_state_vscdb(
                root / "User" / "globalStorage" / "state.vscdb"
            ),
        },
    }
    stores = report["stores"]
    ok = report["exists"] and all(
        s["exists"] and "error" not in s for s in stores.values()
    )
    report["ok"] = ok

    if args.json:
        _print_json(report)
    else:
        s = stores["sessions_db"]
        detail = (
            f"v{s['schema_version']} {s['counts']}"
            if s.get("schema_version")
            else s.get("error", "missing")
        )
        print(f"sessions.db     {'OK' if s['exists'] else 'MISSING'}  {detail}")
        a = stores["acp_messages"]
        detail = (
            f"{a['count']} db file(s)"
            if a.get("count") is not None
            else a.get("error", "missing")
        )
        print(f"acp-messages    {'OK' if a['exists'] else 'MISSING'}  {detail}")
        v = stores["state_vscdb"]
        detail = (
            f"{v['counts']} windsurf_keys={v['windsurf_keys']}"
            if v.get("counts")
            else v.get("error", "missing")
        )
        print(f"state.vscdb     {'OK' if v['exists'] else 'MISSING'}  {detail}")
        print(f"overall: {'OK' if ok else 'DEGRADED'}")
    return 0 if ok else 1


def cmd_contract(args: argparse.Namespace) -> int:
    report = check_contract(args.devin_data_dir)
    _print_json(report)
    return 0 if report["status"] == "ok" else 1


def cmd_make_fixture(args: argparse.Namespace) -> int:
    out = Path(args.output).expanduser()
    created: dict[str, Any]
    if args.kind == "dir":
        created = fixtures.create_devin_data_dir(
            out,
            seed=args.seed,
            n_acp_dbs=args.n_acp_dbs,
            schema_version=args.schema_version,
            n_sessions=args.n_sessions,
        )
    elif args.kind == "sessions":
        created = {
            "sessions_db": fixtures.create_sessions_db(
                out,
                schema_version=args.schema_version,
                seed=args.seed,
                n_sessions=args.n_sessions,
            )
        }
    elif args.kind == "acp-messages":
        created = {"acp_messages_db": fixtures.create_acp_messages_db(out, seed=args.seed)}
    else:
        created = {"state_vscdb": fixtures.create_state_vscdb(out, seed=args.seed)}
    created["synthetic"] = True
    created["seed"] = args.seed
    _print_json({k: [str(p) for p in v] if isinstance(v, list) else str(v)
                 for k, v in created.items()})
    return 0


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="devin-inspect",
        description="Read-only inspection of Devin's local session stores.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("schema", help="print the schema-detection contract")
    p.add_argument("path", help="path to a sessions.db")
    p.add_argument("--json", action="store_true", help="JSON output (default)")
    p.set_defaults(func=cmd_schema)

    p = sub.add_parser("sessions", help="list sessions in a sessions.db")
    p.add_argument("path", help="path to a sessions.db")
    p.add_argument("--limit", type=int, default=None, metavar="N",
                   help="show at most N sessions")
    p.add_argument("--json", action="store_true", help="JSON output")
    p.set_defaults(func=cmd_sessions)

    p = sub.add_parser("health", help="check a Devin data directory")
    p.add_argument("devin_data_dir",
                   help="Devin data root (contains cli/ and User/)")
    p.add_argument("--json", action="store_true", help="JSON output")
    p.set_defaults(func=cmd_health)

    p = sub.add_parser(
        "make-fixture",
        help="write deterministic synthetic Devin stores (for tests/demos)",
    )
    p.add_argument("output",
                   help="output dir (kind=dir) or file path (other kinds)")
    p.add_argument("--kind", choices=["dir", "sessions", "acp-messages", "state-vscdb"],
                   default="dir", help="what to generate (default: full data dir)")
    p.add_argument("--seed", type=int, default=fixtures.DEFAULT_SEED,
                   help="deterministic seed (default: %(default)s)")
    p.add_argument("--schema-version", type=int,
                   default=fixtures.LATEST_KNOWN_SCHEMA,
                   help="sessions.db schema version; >17 exercises the "
                        "unknown-version path (default: %(default)s)")
    p.add_argument("--n-sessions", type=int, default=3,
                   help="sessions to generate (default: %(default)s)")
    p.add_argument("--n-acp-dbs", type=int, default=2,
                   help="acp-messages DBs in kind=dir (default: %(default)s)")
    p.set_defaults(func=cmd_make_fixture)

    p = sub.add_parser(
        "contract",
        help="unified drift contract: schema version, acp-messages meta, "
             "usage shape — one report for all stores",
    )
    p.add_argument("devin_data_dir",
                   help="Devin data root (contains cli/ and User/)")
    p.set_defaults(func=cmd_contract)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except SchemaError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (sqlite3.Error, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
