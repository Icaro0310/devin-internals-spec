"""Offline-core guard: the core must not open sockets.

Release checklist item: "no-network core test (CI): fails if the core
opens a socket". An autouse fixture monkeypatches ``socket.socket.connect``,
``socket.socket.connect_ex`` and ``socket.create_connection`` to raise
``OfflineCoreError`` for the duration of every test in this file, then the
tests run the repo's core operations end to end. This is a guard, not a
mock: any in-process network access fails the suite.

Intentional online paths are excluded by design: none exist in this repo's
core (all subcommands are read-only on local SQLite stores). Sibling repos'
online paths (qa-pack ``--online``, evals judge/ab-run via bridge
subprocess, weekly report fetchers) spawn subprocesses or require explicit
opt-in flags, so an in-process socket block cannot reach them anyway.

Opt-out: mark a test ``@pytest.mark.network`` to run it without the socket
block (reserved for future tests that intentionally exercise the network).

Run with: ``PYTHONPATH=src python -m pytest tests/test_offline_core.py``
"""

from __future__ import annotations

import json
import socket

import pytest

from devin_internals.cli import main


class OfflineCoreError(RuntimeError):
    """Raised when core code tries to open a network connection."""


def _offline_fail(*args, **kwargs):
    raise OfflineCoreError("core opened a socket during the offline-core test")


@pytest.fixture(autouse=True)
def _block_sockets(request, monkeypatch):
    """Block all outbound sockets; opt out with ``@pytest.mark.network``."""
    if request.node.get_closest_marker("network"):
        return
    monkeypatch.setattr(socket.socket, "connect", _offline_fail)
    monkeypatch.setattr(socket.socket, "connect_ex", _offline_fail)
    monkeypatch.setattr(socket, "create_connection", _offline_fail)


def test_socket_block_is_active():
    """Sanity check: the guard itself raises on any connect attempt."""
    with pytest.raises(OfflineCoreError):
        socket.create_connection(("127.0.0.1", 1), timeout=0.01)
    with pytest.raises(OfflineCoreError):
        socket.socket().connect(("127.0.0.1", 1))


def test_make_fixture_contract_and_vscdb_scan_offline(tmp_path, capsys):
    data_dir = tmp_path / "devin-data"

    assert main(["make-fixture", str(data_dir)]) == 0
    capsys.readouterr()

    # contract on the freshly generated fixture dir
    assert main(["contract", str(data_dir)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "ok"

    # vscdb-scan on the synthetic state.vscdb inside the fixture
    vscdb = data_dir / "User" / "globalStorage" / "state.vscdb"
    assert vscdb.is_file()
    assert main(["vscdb-scan", str(vscdb), "--json"]) == 0
    scan_report = json.loads(capsys.readouterr().out)
    assert scan_report["total_keys"] > 0
