"""Identity tests: stable machine-id (persist once, never regenerate) and
the fail-closed machine profile, anchored under
``<config>/.devin-ecosystem/``.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from devin_internals.identity import (
    DEFAULT_PROFILE,
    machine_id,
    machine_id_path,
    profile,
    profile_path_candidates,
    provenance,
)


def _env(tmp_path: Path) -> dict[str, str]:
    return {"XDG_CONFIG_HOME": str(tmp_path / "xdg-config")}


def _ecosystem(tmp_path: Path) -> Path:
    return tmp_path / "xdg-config" / "Devin" / ".devin-ecosystem"


# ---------------------------------------------------------------------------
# machine_id
# ---------------------------------------------------------------------------


def test_machine_id_path_anchors_under_devin_config(tmp_path):
    env = _env(tmp_path)

    assert machine_id_path(env, "linux") == (
        _ecosystem(tmp_path) / "machine-id"
    )


def test_machine_id_creates_stable_id(tmp_path):
    env = _env(tmp_path)

    first = machine_id(env, "linux")
    second = machine_id(env, "linux")

    assert first == second
    assert len(first) == 16
    int(first, 16)  # hex
    path = _ecosystem(tmp_path) / "machine-id"
    assert path.read_text(encoding="utf-8") == first + "\n"


def test_machine_id_is_never_regenerated(tmp_path):
    env = _env(tmp_path)
    path = _ecosystem(tmp_path) / "machine-id"
    path.parent.mkdir(parents=True)
    path.write_text("preexisting12345\n", encoding="utf-8")

    assert machine_id(env, "linux") == "preexisting12345"
    assert path.read_text(encoding="utf-8") == "preexisting12345\n"


def test_machine_id_env_override_wins_and_writes_nothing(tmp_path):
    env = _env(tmp_path)
    env["DEVIN_MACHINE_ID"] = " env-id-override "

    assert machine_id(env, "linux") == "env-id-override"
    assert not (_ecosystem(tmp_path) / "machine-id").exists()


def test_machine_id_explicit_ecosystem_dir(tmp_path):
    eco = tmp_path / "elsewhere" / ".devin-ecosystem"

    value = machine_id({}, "linux", ecosystem_dir=eco)

    assert (eco / "machine-id").read_text(encoding="utf-8") == value + "\n"


def test_machine_id_file_is_private(tmp_path):
    if os.name == "nt":
        return  # POSIX modes are a no-op on Windows filesystems
    env = _env(tmp_path)
    machine_id(env, "linux")

    mode = stat.S_IMODE((_ecosystem(tmp_path) / "machine-id").stat().st_mode)
    assert mode == 0o600


def test_machine_id_concurrent_loser_adopts_winner(tmp_path, monkeypatch):
    """Loser of the O_EXCL create race reads back the winner's id —
    provenance never splits."""
    env = _env(tmp_path)
    path = _ecosystem(tmp_path) / "machine-id"

    def losing_open(*args, **kwargs):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("0123456789abcdef\n", encoding="utf-8")
        raise FileExistsError(path)

    monkeypatch.setattr(os, "open", losing_open)

    assert machine_id(env, "linux") == "0123456789abcdef"
    assert path.read_text(encoding="utf-8") == "0123456789abcdef\n"


def test_machine_id_reclaims_stale_empty_file(tmp_path):
    """An empty file (crashed publisher) is reclaimed, not adopted."""
    env = _env(tmp_path)
    path = _ecosystem(tmp_path) / "machine-id"
    path.parent.mkdir(parents=True)
    path.touch()

    value = machine_id(env, "linux")

    assert len(value) == 16
    int(value, 16)
    assert path.read_text(encoding="utf-8") == value + "\n"
    assert machine_id(env, "linux") == value


def test_machine_id_reclaims_undecodable_file(tmp_path):
    """A corrupt (non-UTF-8) file yields a usable id instead of raising."""
    env = _env(tmp_path)
    path = _ecosystem(tmp_path) / "machine-id"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\xff\xfe invalid \x00")

    value = machine_id(env, "linux")

    assert len(value) == 16
    int(value, 16)
    assert path.read_text(encoding="utf-8") == value + "\n"


def test_machine_id_unreadable_file_never_replaced(tmp_path):
    """An existing but unreadable id propagates — it is never silently
    replaced by a fresh one."""
    if os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0):
        return  # chmod 000 does not block root; POSIX modes n/a on Windows
    env = _env(tmp_path)
    path = _ecosystem(tmp_path) / "machine-id"
    path.parent.mkdir(parents=True)
    path.write_text("preexisting12345\n", encoding="utf-8")
    path.chmod(0o000)

    try:
        with pytest.raises(OSError):
            machine_id(env, "linux")
    finally:
        path.chmod(0o600)

    assert path.read_text(encoding="utf-8") == "preexisting12345\n"


# ---------------------------------------------------------------------------
# profile
# ---------------------------------------------------------------------------


def test_profile_env_wins(tmp_path):
    env = _env(tmp_path)
    env["DEVIN_ECOSYSTEM_PROFILE"] = "Personal"

    assert profile(env, "linux") == "personal"


def test_profile_env_unknown_fails_closed(tmp_path):
    env = _env(tmp_path)
    env["DEVIN_ECOSYSTEM_PROFILE"] = "enterprise"

    assert profile(env, "linux") == DEFAULT_PROFILE == "corporate"


def test_profile_defaults_corporate_when_unset(tmp_path):
    assert profile(_env(tmp_path), "linux") == "corporate"


def test_profile_reads_canonical_ecosystem_file(tmp_path):
    env = _env(tmp_path)
    eco = _ecosystem(tmp_path)
    eco.mkdir(parents=True)
    (eco / "devin-profile.json").write_text(
        json.dumps({"profile": "personal"}), encoding="utf-8"
    )

    assert profile(env, "linux") == "personal"


def test_profile_reads_legacy_config_root_file(tmp_path):
    """Drifted copies wrote ``<config>/devin-profile.json`` — still read,
    after the canonical ecosystem location."""
    env = _env(tmp_path)
    config = tmp_path / "xdg-config" / "Devin"
    config.mkdir(parents=True)
    (config / "devin-profile.json").write_text(
        json.dumps({"profile": "personal"}), encoding="utf-8"
    )

    assert profile(env, "linux") == "personal"


def test_profile_canonical_beats_legacy(tmp_path):
    env = _env(tmp_path)
    eco = _ecosystem(tmp_path)
    eco.mkdir(parents=True)
    (eco / "devin-profile.json").write_text(
        json.dumps({"profile": "personal"}), encoding="utf-8"
    )
    (eco.parent / "devin-profile.json").write_text(
        json.dumps({"profile": "corporate"}), encoding="utf-8"
    )

    assert profile(env, "linux") == "personal"


def test_profile_bare_string_value(tmp_path):
    env = _env(tmp_path)
    eco = _ecosystem(tmp_path)
    eco.mkdir(parents=True)
    (eco / "devin-profile.json").write_text('"personal"', encoding="utf-8")

    assert profile(env, "linux") == "personal"


def test_profile_broken_json_fails_closed(tmp_path):
    env = _env(tmp_path)
    eco = _ecosystem(tmp_path)
    eco.mkdir(parents=True)
    (eco / "devin-profile.json").write_text("{broken", encoding="utf-8")

    assert profile(env, "linux") == "corporate"


def test_profile_unknown_file_value_fails_closed(tmp_path):
    env = _env(tmp_path)
    eco = _ecosystem(tmp_path)
    eco.mkdir(parents=True)
    (eco / "devin-profile.json").write_text(
        json.dumps({"profile": "enterprise"}), encoding="utf-8"
    )

    assert profile(env, "linux") == "corporate"


def test_profile_invalid_canonical_fails_closed_over_legacy(tmp_path):
    """A present-but-invalid canonical file must not fall through to a
    less strict legacy value."""
    env = _env(tmp_path)
    eco = _ecosystem(tmp_path)
    eco.mkdir(parents=True)
    (eco / "devin-profile.json").write_text(
        json.dumps({"profile": "enterprise"}), encoding="utf-8"
    )
    (eco.parent / "devin-profile.json").write_text(
        json.dumps({"profile": "personal"}), encoding="utf-8"
    )

    assert profile(env, "linux") == "corporate"


def test_profile_undecodable_file_fails_closed(tmp_path):
    env = _env(tmp_path)
    eco = _ecosystem(tmp_path)
    eco.mkdir(parents=True)
    (eco / "devin-profile.json").write_bytes(b"\xff\xfe\x00")

    assert profile(env, "linux") == "corporate"


def test_profile_path_candidates_order(tmp_path):
    env = _env(tmp_path)
    eco = _ecosystem(tmp_path)

    assert profile_path_candidates(env, "linux") == [
        eco / "devin-profile.json",
        eco.parent / "devin-profile.json",
    ]


# ---------------------------------------------------------------------------
# provenance
# ---------------------------------------------------------------------------


def test_provenance_combines_both(tmp_path):
    env = _env(tmp_path)
    env["DEVIN_ECOSYSTEM_PROFILE"] = "personal"

    prov = provenance(env, "linux")

    assert prov["profile"] == "personal"
    assert prov["machine_id"] == machine_id(env, "linux")


def test_provenance_uses_sys_platform_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))

    prov = provenance()

    assert (tmp_path / "cfg" / "Devin" / ".devin-ecosystem" / "machine-id").is_file()
    assert prov["profile"] == "corporate"
