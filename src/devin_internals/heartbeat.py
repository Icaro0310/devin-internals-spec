"""Universal heartbeat ledger — one shared JSONL file every tool beats into.

Any tool, cron job or daemon in the ecosystem appends a one-line JSON
record per run so a silence sensor (``ecosystem_sync --freshness`` and
friends) can distinguish *dead-but-alive* components — a process that is
scheduled but stopped producing beats — from healthy ones. Spec:
``docs/HEARTBEAT.md``.

This module is **single-file and stdlib-only on purpose**: other repos
vendor it verbatim, so it must never import from ``devin_internals`` or
any third-party package — ``python3 heartbeat.py emit ...`` has to work
from any directory. ``heartbeat.js`` (same directory) is the zero-dep
ESM mirror for node consumers; both write the same line contract.

Ledger location, first match wins::

    $DEVIN_HEARTBEAT_FILE
    $XDG_STATE_HOME/devin/heartbeats.jsonl
    ~/.local/state/devin/heartbeats.jsonl

Design rules (do not regress — vendored copies depend on them):

- ``emit_heartbeat`` NEVER raises. A broken ledger must not break the
  tool it observes — all I/O and path resolution is wrapped.
- Tool names are sanitized to ``[a-z0-9-]{1,64}`` at write time so the
  reader contract stays closed.
- Readers are fail-open: malformed lines are skipped, a missing file
  reads as an empty map.
- ``hb_run``/``hb_probe`` wrap a command without a shell, beat success
  iff ``rc == 0``, and return the command's rc so crontab semantics are
  unchanged — instrument crontabs, not tool internals.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path

LEDGER_ENV = "DEVIN_HEARTBEAT_FILE"
"""Env var overriding the ledger path (checked first by ``ledger_path``)."""

TOOL_RE = re.compile(r"^[a-z0-9-]{1,64}$")
"""The closed vocabulary for ``tool`` — enforced via ``_sanitize_tool``."""

DETAIL_MAX_CHARS = 200
"""``detail`` is truncated to this many characters at write time."""

RUN_TAIL_CHARS = 120
"""Chars of combined command output kept in the ``hb_run`` failure detail."""


def ledger_path(environ: dict[str, str] | None = None) -> Path:
    """Resolve the ledger file location.

    ``DEVIN_HEARTBEAT_FILE`` wins; then
    ``$XDG_STATE_HOME/devin/heartbeats.jsonl``; finally
    ``~/.local/state/devin/heartbeats.jsonl``. ``environ`` is injectable
    for tests — nothing is created, this only resolves a path.
    """
    env = os.environ if environ is None else environ
    override = env.get(LEDGER_ENV)
    if override:
        return Path(override).expanduser()
    state_home = env.get("XDG_STATE_HOME")
    root = (
        Path(state_home).expanduser()
        if state_home
        else Path.home() / ".local" / "state"
    )
    return root / "devin" / "heartbeats.jsonl"


LEDGER = ledger_path()
"""Ledger path resolved at import time — informational only. All write
and read paths below re-resolve lazily so env changes (tests, vendored
entrypoints setting ``DEVIN_HEARTBEAT_FILE`` late) take effect; prefer
:func:`ledger_path` over this constant."""


def _safe_ledger_path() -> Path:
    """``ledger_path()`` that cannot raise — emit must never fail."""
    try:
        return ledger_path()
    except Exception:  # noqa: BLE001 - fail-open contract: emit must never raise
        return Path("heartbeats.jsonl")


def _sanitize_tool(tool: object) -> str:
    """Coerce ``tool`` to the ``[a-z0-9-]{1,64}`` contract; never raises.

    Lowercases, maps every run of invalid characters to a single ``-``,
    strips leading/trailing dashes, truncates to 64 chars. Empty results
    (no valid characters at all) fall back to ``"unknown"`` so the beat
    still records *something* fired.
    """
    try:
        name = re.sub(r"[^a-z0-9]+", "-", str(tool).lower()).strip("-")
        name = name[:64].strip("-")
        return name or "unknown"
    except Exception:  # noqa: BLE001 - sanitization must never raise
        return "unknown"


def emit_heartbeat(
    tool: str, success: bool = True, detail: str | None = None
) -> Path:
    """Append one beat to the ledger and return the path written to.

    Line contract::

        {"ts": <epoch float>, "tool": "<sanitized>",
         "event": "success"|"failure", "detail": "<short>"|null}

    Creates the ledger directory on first use. NEVER raises — a broken
    or unwritable ledger must not break the tool it observes, so every
    failure (I/O, path resolution, serialization) is swallowed.
    """
    path = _safe_ledger_path()
    try:
        record = {
            "ts": time.time(),
            "tool": _sanitize_tool(tool),
            "event": "success" if success else "failure",
            "detail": (
                None
                if detail is None
                else str(detail)[:DETAIL_MAX_CHARS]
            ),
        }
        line = json.dumps(record, separators=(",", ":"), ensure_ascii=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:  # noqa: BLE001,S110 - the ledger must never break the tool it observes
        pass
    return path


def read_heartbeats(path: Path | str | None = None) -> dict[str, dict]:
    """Fold the ledger into per-tool last-seen timestamps.

    Returns ``{tool: {"last_success_at": ts|None,
    "last_failure_at": ts|None, "last_detail": str|None}}`` —
    ``last_detail`` comes from the newest beat recorded for that tool
    (max ``ts``, later lines win ties). Fail-open by contract: a missing
    file reads as ``{}`` and malformed lines (bad JSON, non-dict, missing
    ``tool``/``event``/``ts``, unknown event, non-numeric ts) are skipped
    — a corrupt ledger degrades the freshness signal, it never crashes
    the sensor.
    """
    ledger = _safe_ledger_path() if path is None else Path(path)
    out: dict[str, dict] = {}
    try:
        lines = ledger.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
    except OSError:
        return out
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        tool = rec.get("tool")
        event = rec.get("event")
        ts = rec.get("ts")
        if not isinstance(tool, str) or not tool:
            continue
        if event not in ("success", "failure"):
            continue
        # bool is a subclass of int — a JSON ``true`` is not a timestamp
        if not isinstance(ts, (int, float)) or isinstance(ts, bool):
            continue
        slot = out.setdefault(
            tool,
            {
                "last_success_at": None,
                "last_failure_at": None,
                "last_detail": None,
                "_latest_ts": float("-inf"),
            },
        )
        key = "last_success_at" if event == "success" else "last_failure_at"
        if slot[key] is None or ts > slot[key]:
            slot[key] = ts
        if ts >= slot["_latest_ts"]:
            slot["_latest_ts"] = ts
            detail = rec.get("detail")
            slot["last_detail"] = detail if isinstance(detail, str) else None
    for slot in out.values():
        del slot["_latest_ts"]
    return out


def _run_wrapped(tool: str, argv: Sequence[str]) -> int:
    """Run ``argv`` without a shell, beat the outcome, return its rc.

    The child's combined stdout+stderr is captured, echoed back to this
    process's stdout (so cron mail and caller logs keep working), and its
    last :data:`RUN_TAIL_CHARS` chars go into the failure detail as
    ``rc=<n> <tail>``. A command that cannot be spawned beats failure
    with ``spawn-error`` and returns 127 — the shell's
    command-not-found convention — so wrappers stay indistinguishable
    from the commands they wrap.
    """
    if not argv:
        emit_heartbeat(tool, success=False, detail="empty argv")
        return 127
    try:
        proc = subprocess.run(
            list(argv),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
    except OSError as exc:
        emit_heartbeat(tool, success=False, detail=f"spawn-error: {exc}")
        return 127
    out = proc.stdout or b""
    if out:
        _echo(out)
    if proc.returncode == 0:
        emit_heartbeat(tool, success=True)
    else:
        tail = out.decode("utf-8", errors="replace")[-RUN_TAIL_CHARS:]
        emit_heartbeat(
            tool,
            success=False,
            detail=f"rc={proc.returncode} {tail}".strip(),
        )
    return proc.returncode


def _echo(out: bytes) -> None:
    """Replay captured child output — fail-open, stdout may be unusual."""
    try:
        sys.stdout.buffer.write(out)
        sys.stdout.buffer.flush()
        return
    except (AttributeError, OSError):
        pass
    try:
        sys.stdout.write(out.decode("utf-8", errors="replace"))
        sys.stdout.flush()
    except Exception:  # noqa: BLE001,S110 - output passthrough is best-effort
        pass


def hb_run(tool: str, argv: Sequence[str]) -> int:
    """``hb run <tool> -- <cmd...>``: wrap a scheduled command.

    Runs ``argv`` without a shell, beats ``success`` iff ``rc == 0``
    (otherwise ``failure`` with detail ``rc=<n>`` plus the last
    :data:`RUN_TAIL_CHARS` chars of combined output), and returns the
    command's rc so callers and crontabs see the same status as before.
    """
    return _run_wrapped(tool, argv)


def hb_probe(tool: str, argv: Sequence[str]) -> int:
    """``hb probe <tool> -- <cmd...>``: same contract as :func:`hb_run`.

    Separate name for daemon health checks — ``hb probe office -- curl
    -sf http://127.0.0.1:PORT/healthz`` reads as a liveness probe in a
    crontab while producing the identical ledger record.
    """
    return _run_wrapped(tool, argv)


def _usage() -> None:
    sys.stderr.write(
        "usage:\n"
        "  heartbeat.py emit  <tool> [--fail] [--detail txt]\n"
        "  heartbeat.py run   <tool> -- <cmd> [args...]\n"
        "  heartbeat.py probe <tool> -- <cmd> [args...]\n"
    )


def _main_emit(argv: list[str]) -> int:
    """``emit`` subcommand — exit 0 always, even on bad args."""
    parser = argparse.ArgumentParser(prog="heartbeat.py emit")
    parser.add_argument("tool")
    parser.add_argument(
        "--fail", action="store_true", help="record a failure beat"
    )
    parser.add_argument("--detail", default=None)
    try:
        ns = parser.parse_args(argv)
        emit_heartbeat(ns.tool, success=not ns.fail, detail=ns.detail)
    except SystemExit:
        pass  # argparse errors/help must not fail the caller
    except Exception:  # noqa: BLE001,S110 - emit exits 0 always
        pass
    return 0


def _main_wrap(argv: list[str], fn) -> int:
    """Shared ``run``/``probe`` parsing: ``<tool> [--] <cmd...>``."""
    if not argv:
        _usage()
        return 2
    tool, rest = argv[0], argv[1:]
    if rest and rest[0] == "--":
        rest = rest[1:]
    return fn(tool, rest)


def main(argv: list[str] | None = None) -> int:
    """CLI entry: ``emit`` (always 0) | ``run``/``probe`` (child's rc)."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        _usage()
        return 0
    cmd, rest = args[0], args[1:]
    if cmd == "emit":
        return _main_emit(rest)
    if cmd == "run":
        return _main_wrap(rest, hb_run)
    if cmd == "probe":
        return _main_wrap(rest, hb_probe)
    _usage()
    return 0


if __name__ == "__main__":
    sys.exit(main())
