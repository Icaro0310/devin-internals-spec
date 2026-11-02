"""Heartbeat ledger tests — JSONL contract, fail-open emit, max-ts
aggregation, run/probe wrapper rc passthrough, tool sanitization and the
node mirror (skipped when node is absent).

Hermetic: every test points ``DEVIN_HEARTBEAT_FILE`` at ``tmp_path``;
nothing touches the real ``~/.local/state``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from devin_internals import heartbeat
from devin_internals.heartbeat import (
    DETAIL_MAX_CHARS,
    LEDGER_ENV,
    emit_heartbeat,
    hb_probe,
    hb_run,
    ledger_path,
    read_heartbeats,
)

HEARTBEAT_PY = Path(heartbeat.__file__)
HEARTBEAT_JS = HEARTBEAT_PY.with_suffix(".js")
NODE = shutil.which("node")


@pytest.fixture
def ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "deep" / "state" / "devin" / "heartbeats.jsonl"
    monkeypatch.setenv(LEDGER_ENV, str(path))
    return path


def _lines(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ---------------------------------------------------------------------------
# ledger_path resolution
# ---------------------------------------------------------------------------


def test_ledger_path_env_override_wins(tmp_path: Path) -> None:
    env = {LEDGER_ENV: str(tmp_path / "x.jsonl"), "XDG_STATE_HOME": "/nope"}
    assert ledger_path(env) == tmp_path / "x.jsonl"


def test_ledger_path_xdg_fallback() -> None:
    assert ledger_path({"XDG_STATE_HOME": "/state"}) == Path(
        "/state/devin/heartbeats.jsonl"
    )


def test_ledger_path_home_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ``Path.home()`` honors HOME on POSIX, USERPROFILE on Windows — set
    # both so the test is portable.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert ledger_path({}) == (
        tmp_path / ".local" / "state" / "devin" / "heartbeats.jsonl"
    )


# ---------------------------------------------------------------------------
# emit
# ---------------------------------------------------------------------------


def test_emit_writes_valid_jsonl_and_creates_dirs(ledger: Path) -> None:
    path = emit_heartbeat("scout", detail="ok")
    assert path == ledger
    assert ledger.is_file()
    (rec,) = _lines(ledger)
    assert rec["tool"] == "scout"
    assert rec["event"] == "success"
    assert rec["detail"] == "ok"
    assert isinstance(rec["ts"], float)


def test_emit_failure_event(ledger: Path) -> None:
    emit_heartbeat("job", success=False, detail="rc=2")
    (rec,) = _lines(ledger)
    assert rec["event"] == "failure"
    assert rec["detail"] == "rc=2"


def test_emit_detail_defaults_to_null(ledger: Path) -> None:
    emit_heartbeat("job")
    (rec,) = _lines(ledger)
    assert rec["detail"] is None


def test_emit_never_raises_on_unwritable_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A regular file where the ledger dir must be — mkdir -p fails on
    # every platform, root or not.
    blocker = tmp_path / "blocker"
    blocker.write_text("file, not a dir")
    monkeypatch.setenv(LEDGER_ENV, str(blocker / "sub" / "hb.jsonl"))
    path = emit_heartbeat("t")  # must not raise
    assert path == blocker / "sub" / "hb.jsonl"
    assert not path.exists()


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("My Tool!!", "my-tool"),
        ("UPPER_ok", "upper-ok"),
        ("--lead--trail--", "lead-trail"),
        ("spaces  and\ttabs", "spaces-and-tabs"),
        ("café", "caf"),
        ("!!!", "unknown"),
        ("", "unknown"),
        ("a" * 100, "a" * 64),
        ("x-" * 40 + "x", ("x-" * 32).rstrip("-")),
    ],
)
def test_tool_sanitization(ledger: Path, raw: str, want: str) -> None:
    emit_heartbeat(raw)
    (rec,) = _lines(ledger)
    assert rec["tool"] == want


def test_detail_truncated_at_write(ledger: Path) -> None:
    emit_heartbeat("t", detail="x" * (DETAIL_MAX_CHARS + 50))
    (rec,) = _lines(ledger)
    assert rec["detail"] == "x" * DETAIL_MAX_CHARS


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------


def test_read_aggregates_max_ts_per_event(ledger: Path) -> None:
    ledger.parent.mkdir(parents=True)
    # last lines are malformed — all skipped by the reader
    ledger.write_text(
        '{"ts": 10, "tool": "a", "event": "success", "detail": "s1"}\n'
        '{"ts": 30, "tool": "a", "event": "failure", "detail": "f1"}\n'
        '{"ts": 20, "tool": "a", "event": "success", "detail": "s2"}\n'
        '{"ts": 5, "tool": "b", "event": "failure", "detail": null}\n'
        "\n"
        "not json\n"
        "[1, 2]\n"
        '{"tool": "a"}\n'
        '{"tool": "a", "event": "weird", "ts": 99}\n'
        '{"tool": "a", "event": "success", "ts": "nope"}\n'
        '{"tool": "a", "event": "success", "ts": true}\n'
        '{"tool": "", "event": "success", "ts": 99}\n'
        '{"tool": 7, "event": "success", "ts": 99}\n',
        encoding="utf-8",
    )
    beats = read_heartbeats(ledger)
    assert set(beats) == {"a", "b"}
    assert beats["a"]["last_success_at"] == 20
    assert beats["a"]["last_failure_at"] == 30
    # last_detail comes from the newest beat overall (ts=30)
    assert beats["a"]["last_detail"] == "f1"
    assert beats["b"]["last_success_at"] is None
    assert beats["b"]["last_failure_at"] == 5
    assert beats["b"]["last_detail"] is None


def test_read_missing_file_is_empty(tmp_path: Path) -> None:
    assert read_heartbeats(tmp_path / "nope.jsonl") == {}


def test_read_corrupt_file_skips_bad_lines(tmp_path: Path) -> None:
    path = tmp_path / "hb.jsonl"
    path.write_bytes(b"\xff\xfe{bad\n" + b'{"ts":1,"tool":"t","event":"success","detail":null}\n')
    beats = read_heartbeats(path)
    assert beats["t"]["last_success_at"] == 1


# ---------------------------------------------------------------------------
# run / probe wrappers
# ---------------------------------------------------------------------------


def test_hb_run_emits_success_on_rc0(ledger: Path) -> None:
    rc = hb_run("job", [sys.executable, "-c", "pass"])
    assert rc == 0
    beats = read_heartbeats(ledger)
    assert beats["job"]["last_success_at"] is not None
    assert beats["job"]["last_failure_at"] is None


def test_hb_run_failure_passthrough_and_detail(ledger: Path) -> None:
    rc = hb_run(
        "job",
        [
            sys.executable,
            "-c",
            "import sys; print('marker-xyz'); sys.exit(3)",
        ],
    )
    assert rc == 3
    beats = read_heartbeats(ledger)
    assert beats["job"]["last_failure_at"] is not None
    assert beats["job"]["last_success_at"] is None
    detail = beats["job"]["last_detail"]
    assert detail.startswith("rc=3")
    assert "marker-xyz" in detail


def test_hb_run_missing_command_is_127(ledger: Path) -> None:
    rc = hb_run("job", ["definitely-not-a-binary-xyz"])
    assert rc == 127
    detail = read_heartbeats(ledger)["job"]["last_detail"]
    assert detail.startswith("spawn-error")


def test_hb_run_empty_argv_is_127(ledger: Path) -> None:
    assert hb_run("job", []) == 127
    assert read_heartbeats(ledger)["job"]["last_detail"] == "empty argv"


def test_hb_probe_same_contract(ledger: Path) -> None:
    rc = hb_probe("daemon", [sys.executable, "-c", "pass"])
    assert rc == 0
    assert read_heartbeats(ledger)["daemon"]["last_success_at"] is not None


def test_hb_run_replays_child_output(
    ledger: Path, capfd: pytest.CaptureFixture
) -> None:
    hb_run("job", [sys.executable, "-c", "print('child-out')"])
    assert "child-out" in capfd.readouterr().out


# ---------------------------------------------------------------------------
# CLI (runs the file directly — same path a vendored copy takes)
# ---------------------------------------------------------------------------


def test_cli_emit_success_and_fail(ledger: Path) -> None:
    ok = subprocess.run(
        [sys.executable, str(HEARTBEAT_PY), "emit", "clitool"],
        check=False, env=dict(os.environ),
    )
    assert ok.returncode == 0
    fail = subprocess.run(
        [
            sys.executable,
            str(HEARTBEAT_PY),
            "emit",
            "clitool",
            "--fail",
            "--detail",
            "boom",
        ],
        check=False, env=dict(os.environ),
    )
    assert fail.returncode == 0
    recs = _lines(ledger)
    assert recs[0]["event"] == "success"
    assert recs[1]["event"] == "failure"
    assert recs[1]["detail"] == "boom"


def test_cli_emit_bad_args_still_exits_0(ledger: Path) -> None:
    res = subprocess.run(
        [sys.executable, str(HEARTBEAT_PY), "emit"],
        check=False, env=dict(os.environ),
        capture_output=True,
    )
    assert res.returncode == 0


def test_cli_run_passthrough(ledger: Path) -> None:
    res = subprocess.run(
        [
            sys.executable,
            str(HEARTBEAT_PY),
            "run",
            "clirun",
            "--",
            sys.executable,
            "-c",
            "import sys; sys.exit(5)",
        ],
        check=False, env=dict(os.environ),
    )
    assert res.returncode == 5
    detail = read_heartbeats(ledger)["clirun"]["last_detail"]
    assert detail.startswith("rc=5")


# ---------------------------------------------------------------------------
# node mirror — exercised through the real CLI, skipped without node
# ---------------------------------------------------------------------------


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_js_emit_and_run(ledger: Path) -> None:
    env = dict(os.environ)
    emit = subprocess.run(
        [NODE, str(HEARTBEAT_JS), "emit", "js-tool", "--detail", "hi"],
        check=False, env=env,
    )
    assert emit.returncode == 0
    fail = subprocess.run(
        [NODE, str(HEARTBEAT_JS), "emit", "js-tool", "--fail"],
        check=False, env=env,
    )
    assert fail.returncode == 0
    run = subprocess.run(
        [
            NODE,
            str(HEARTBEAT_JS),
            "run",
            "js-run",
            "--",
            NODE,
            "-e",
            "process.exit(4)",
        ],
        check=False, env=env,
    )
    assert run.returncode == 4
    # cross-language contract: the python reader folds node-written lines
    beats = read_heartbeats(ledger)
    assert beats["js-tool"]["last_success_at"] is not None
    assert beats["js-tool"]["last_failure_at"] is not None
    assert beats["js-run"]["last_failure_at"] is not None
    assert beats["js-run"]["last_detail"].startswith("rc=4")


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_js_module_smoke(ledger: Path) -> None:
    # import + API surface via node -e (ESM); the ``ledger`` fixture's env
    # points the node's readHeartbeats() at the same tmp file
    script = (
        f"import {{ emitHeartbeat, readHeartbeats }} from"
        f" {json.dumps(HEARTBEAT_JS.as_uri())};"
        " emitHeartbeat('Smoke Tool', {success: true, detail: 'x'});"
        " const b = readHeartbeats();"
        " if (b['smoke-tool'].last_success_at == null) process.exit(9);"
    )
    res = subprocess.run(
        [NODE, "--input-type=module", "-e", script],
        check=False,
        env=dict(os.environ),
    )
    assert res.returncode == 0
