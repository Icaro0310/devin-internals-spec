"""Store-location tests: platform defaults, env overrides, XDG fallbacks,
candidate ordering and the resolved ``DevinPaths`` view.

All tests pass ``environ``/``platform`` explicitly and point XDG/APPDATA
roots at ``tmp_path`` — nothing ever touches the real ``~/.config`` or
``~/.local/share``.
"""

from __future__ import annotations

import sys
from pathlib import Path

from devin_internals.paths import (
    DevinPaths,
    acp_messages_dir_candidates,
    credentials_toml_candidates,
    default_config_dir,
    default_data_dir,
    ecosystem_anchor_dir,
    first_existing,
    resolve,
    session_locks_dir_candidates,
    sessions_db_candidates,
    state_vscdb_candidates,
)


def _linux_env(tmp_path: Path) -> dict[str, str]:
    return {
        "XDG_DATA_HOME": str(tmp_path / "xdg-data"),
        "XDG_CONFIG_HOME": str(tmp_path / "xdg-config"),
    }


def _win_env(tmp_path: Path) -> dict[str, str]:
    return {"APPDATA": str(tmp_path / "AppData" / "Roaming")}


# ---------------------------------------------------------------------------
# platform defaults
# ---------------------------------------------------------------------------


def test_linux_defaults(tmp_path):
    env = _linux_env(tmp_path)

    assert default_data_dir(env, "linux") == (
        tmp_path / "xdg-data" / "devin"
    )
    assert default_config_dir(env, "linux") == (
        tmp_path / "xdg-config" / "Devin"
    )


def test_linux_xdg_unset_falls_back_to_home(tmp_path, monkeypatch):
    # ``Path.home()``/``os.path.expanduser`` honor HOME on POSIX,
    # USERPROFILE on Windows — set both so the test is portable.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    env: dict[str, str] = {}

    assert default_data_dir(env, "linux") == (
        tmp_path / ".local" / "share" / "devin"
    )
    assert default_config_dir(env, "linux") == (
        tmp_path / ".config" / "Devin"
    )


def test_windows_defaults(tmp_path):
    env = _win_env(tmp_path)

    assert default_data_dir(env, "win32") == (
        tmp_path / "AppData" / "Roaming" / "devin"
    )
    assert default_config_dir(env, "win32") == (
        tmp_path / "AppData" / "Roaming" / "Devin"
    )


def test_windows_without_appdata_falls_back_to_roaming(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    env: dict[str, str] = {}

    assert default_data_dir(env, "win32") == (
        tmp_path / "AppData" / "Roaming" / "devin"
    )
    assert default_config_dir(env, "win32") == (
        tmp_path / "AppData" / "Roaming" / "Devin"
    )


def test_macos_defaults():
    home = Path.home()

    assert default_data_dir({}, "darwin") == (
        home / "Library" / "Application Support" / "devin"
    )
    # macOS config dir is ``Devin`` — capitalized, like the Electron app.
    assert default_config_dir({}, "darwin") == (
        home / "Library" / "Application Support" / "Devin"
    )


# ---------------------------------------------------------------------------
# env overrides
# ---------------------------------------------------------------------------


def test_env_overrides_win(tmp_path):
    env = _linux_env(tmp_path)
    env["DEVIN_DATA_DIR"] = str(tmp_path / "custom-data")
    env["DEVIN_CONFIG_DIR"] = str(tmp_path / "custom-config")

    assert default_data_dir(env, "linux") == tmp_path / "custom-data"
    assert default_config_dir(env, "linux") == tmp_path / "custom-config"


def test_env_override_beats_platform_defaults(tmp_path):
    env = _win_env(tmp_path)
    env["DEVIN_DATA_DIR"] = str(tmp_path / "d")
    env["DEVIN_CONFIG_DIR"] = str(tmp_path / "c")

    assert default_data_dir(env, "win32") == tmp_path / "d"
    assert default_config_dir(env, "win32") == tmp_path / "c"


def test_env_override_expands_tilde(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    env = {"DEVIN_DATA_DIR": "~/my-devin-data"}

    assert default_data_dir(env, "linux") == tmp_path / "my-devin-data"


# ---------------------------------------------------------------------------
# XDG / legacy probing
# ---------------------------------------------------------------------------


def test_linux_config_prefers_dir_with_user_tree(tmp_path):
    env = _linux_env(tmp_path)
    legacy = tmp_path / "xdg-config" / "devin"
    (legacy / "User").mkdir(parents=True)

    # Only the lowercase candidate exists — it wins over the canonical
    # ``Devin`` name because it holds the ``User/`` tree.
    assert default_config_dir(env, "linux") == legacy


def test_linux_config_canonical_beats_lowercase(tmp_path):
    env = _linux_env(tmp_path)
    canonical = tmp_path / "xdg-config" / "Devin"
    (canonical / "User").mkdir(parents=True)
    (tmp_path / "xdg-config" / "devin" / "User").mkdir(parents=True)

    assert default_config_dir(env, "linux") == canonical


def test_linux_config_fallback_is_capitalized(tmp_path):
    """No ``User/`` anywhere → ``Devin``, never lowercase ``devin``."""
    env = _linux_env(tmp_path)

    assert default_config_dir(env, "linux").name == "Devin"


def test_linux_data_prefers_existing_sessions_db(tmp_path):
    env = _linux_env(tmp_path)
    legacy = tmp_path / "xdg-config" / "devin"
    (legacy / "cli").mkdir(parents=True)
    (legacy / "cli" / "sessions.db").touch()

    # Canonical root has no store; the config-root legacy install wins.
    assert default_data_dir(env, "linux") == legacy


def test_linux_data_canonical_root_wins(tmp_path):
    env = _linux_env(tmp_path)
    canonical = tmp_path / "xdg-data" / "devin"
    (canonical / "cli").mkdir(parents=True)
    (canonical / "cli" / "sessions.db").touch()
    legacy = tmp_path / "xdg-config" / "devin"
    (legacy / "cli").mkdir(parents=True)
    (legacy / "cli" / "sessions.db").touch()

    assert default_data_dir(env, "linux") == canonical


# ---------------------------------------------------------------------------
# resolve()
# ---------------------------------------------------------------------------


def test_resolve_linux_split_layout(tmp_path):
    env = _linux_env(tmp_path)
    data = tmp_path / "xdg-data" / "devin"
    config = tmp_path / "xdg-config" / "Devin"
    (data / "cli").mkdir(parents=True)
    (data / "cli" / "sessions.db").touch()
    (config / "User").mkdir(parents=True)

    paths = resolve(env, "linux")

    assert isinstance(paths, DevinPaths)
    assert paths.data_dir == data
    assert paths.config_dir == config
    assert paths.sessions_db == data / "cli" / "sessions.db"
    assert paths.session_locks_dir == data / "cli" / "session_locks"
    assert paths.credentials_toml == data / "credentials.toml"
    assert paths.acp_messages_dir == config / "User" / "acp-messages"
    assert paths.state_vscdb == (
        config / "User" / "globalStorage" / "state.vscdb"
    )
    # .devin-ecosystem anchors under the Devin config dir — never bare
    # $XDG_CONFIG_HOME (the orchestrator drift this module fixes).
    assert paths.ecosystem_dir == config / ".devin-ecosystem"
    assert paths.ecosystem_dir != tmp_path / "xdg-config" / ".devin-ecosystem"


def test_resolve_frozen_dataclass(tmp_path):
    paths = resolve(_linux_env(tmp_path), "linux")

    try:
        paths.data_dir = tmp_path  # type: ignore[misc]
        raise AssertionError("DevinPaths must be frozen")
    except AttributeError:
        pass


def test_resolve_unified_layout_anchors_user_tree_on_data_root(tmp_path):
    """Fixture-style installs keep ``User/`` under the data root."""
    env = _linux_env(tmp_path)
    env["DEVIN_DATA_DIR"] = str(tmp_path / "devin-data")
    data = tmp_path / "devin-data"
    (data / "User" / "acp-messages").mkdir(parents=True)
    (data / "User" / "globalStorage").mkdir(parents=True)

    paths = resolve(env, "linux")

    assert paths.acp_messages_dir == data / "User" / "acp-messages"
    assert paths.state_vscdb == (
        data / "User" / "globalStorage" / "state.vscdb"
    )


def test_resolve_env_override_anchors_ecosystem(tmp_path):
    env = _linux_env(tmp_path)
    env["DEVIN_CONFIG_DIR"] = str(tmp_path / "explicit-config")

    paths = resolve(env, "linux")

    assert paths.ecosystem_dir == (
        tmp_path / "explicit-config" / ".devin-ecosystem"
    )


def test_resolve_uses_sys_platform_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(sys, "platform", "darwin")
    env = {"XDG_DATA_HOME": str(tmp_path / "xd")}

    paths = resolve(env)  # no platform arg → sys.platform

    assert paths.data_dir == (
        tmp_path / "Library" / "Application Support" / "devin"
    )
    assert paths.config_dir == (
        tmp_path / "Library" / "Application Support" / "Devin"
    )


def test_resolve_uses_os_environ_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVIN_DATA_DIR", str(tmp_path / "env-data"))
    monkeypatch.setenv("DEVIN_CONFIG_DIR", str(tmp_path / "env-config"))

    paths = resolve()

    assert paths.data_dir == tmp_path / "env-data"
    assert paths.config_dir == tmp_path / "env-config"


# ---------------------------------------------------------------------------
# candidate-order helpers
# ---------------------------------------------------------------------------


def test_sessions_db_candidates_data_first(tmp_path):
    data, config = tmp_path / "data", tmp_path / "config"

    cands = sessions_db_candidates(data, config)

    assert cands == [
        data / "cli" / "sessions.db",
        config / "cli" / "sessions.db",
        # legacy split-Linux CLI root: lowercase sibling of the UI root
        tmp_path / "devin" / "cli" / "sessions.db",
    ]


def test_session_locks_dir_candidates_data_first(tmp_path):
    data, config = tmp_path / "data", tmp_path / "config"

    assert session_locks_dir_candidates(data, config) == [
        data / "cli" / "session_locks",
        config / "cli" / "session_locks",
        tmp_path / "devin" / "cli" / "session_locks",
    ]


def test_sessions_db_candidates_cover_lowercase_legacy_root(tmp_path):
    """Split-Linux layout: GUI under ``Devin``, legacy CLI under
    ``devin`` — the lowercase sibling must be probed."""
    env = _linux_env(tmp_path)
    env["DEVIN_DATA_DIR"] = str(tmp_path / "custom-data")
    legacy = tmp_path / "xdg-config" / "devin"
    (legacy / "cli").mkdir(parents=True)
    (legacy / "cli" / "sessions.db").touch()
    (tmp_path / "xdg-config" / "Devin" / "User").mkdir(parents=True)

    paths = resolve(env, "linux")

    assert paths.config_dir.name == "Devin"
    assert first_existing(
        sessions_db_candidates(paths.data_dir, paths.config_dir)
    ) == (legacy / "cli" / "sessions.db")


def test_credentials_toml_candidates_data_first(tmp_path):
    data, config = tmp_path / "data", tmp_path / "config"

    assert credentials_toml_candidates(data, config) == [
        data / "credentials.toml",
        config / "credentials.toml",
    ]


def test_gui_candidates_config_first(tmp_path):
    data, config = tmp_path / "data", tmp_path / "config"

    assert acp_messages_dir_candidates(data, config) == [
        config / "User" / "acp-messages",
        data / "User" / "acp-messages",
    ]
    assert state_vscdb_candidates(data, config) == [
        config / "User" / "globalStorage" / "state.vscdb",
        data / "User" / "globalStorage" / "state.vscdb",
    ]


def test_candidates_dedup_identical_roots(tmp_path):
    """Windows/macOS collapse data+config into one physical dir."""
    same = tmp_path / "devin"

    assert sessions_db_candidates(same, same) == [
        same / "cli" / "sessions.db"
    ]


def test_first_existing(tmp_path):
    missing = tmp_path / "nope"
    present = tmp_path / "yes"
    present.touch()

    assert first_existing([missing, present]) == present
    assert first_existing([missing]) is None
    assert first_existing([]) is None


def test_real_machine_layout(tmp_path):
    """Mirror the verified 2026-10 install: ``~/.config/Devin`` (Electron)
    + ``~/.config/devin`` (CLI) + ``~/.local/share/devin`` (data)."""
    env = _linux_env(tmp_path)
    electron = tmp_path / "xdg-config" / "Devin"
    cli_cfg = tmp_path / "xdg-config" / "devin"
    data = tmp_path / "xdg-data" / "devin"
    (electron / "User" / "globalStorage").mkdir(parents=True)
    (electron / ".devin-ecosystem").mkdir(parents=True)
    cli_cfg.mkdir(parents=True)
    (data / "cli").mkdir(parents=True)
    (data / "cli" / "sessions.db").touch()

    paths = resolve(env, "linux")

    assert paths.config_dir == electron
    assert paths.ecosystem_dir == electron / ".devin-ecosystem"
    assert paths.sessions_db == data / "cli" / "sessions.db"


def test_resolve_empty_data_user_tree_does_not_hide_gui_stores(tmp_path):
    """An empty ``User/`` under the data root must not shadow populated
    GUI stores under the config root."""
    env = _linux_env(tmp_path)
    data = tmp_path / "xdg-data" / "devin"
    config = tmp_path / "xdg-config" / "Devin"
    (data / "cli").mkdir(parents=True)
    (data / "cli" / "sessions.db").touch()
    (data / "User").mkdir(parents=True)  # exists but empty
    (config / "User" / "acp-messages").mkdir(parents=True)
    (config / "User" / "acp-messages" / "a.db").touch()
    (config / "User" / "globalStorage").mkdir(parents=True)
    (config / "User" / "globalStorage" / "state.vscdb").touch()

    paths = resolve(env, "linux")

    assert paths.acp_messages_dir == config / "User" / "acp-messages"
    assert paths.state_vscdb == (
        config / "User" / "globalStorage" / "state.vscdb"
    )


def test_resolve_gui_root_is_per_store(tmp_path):
    """Each GUI store picks the root that actually contains it."""
    env = _linux_env(tmp_path)
    env["DEVIN_DATA_DIR"] = str(tmp_path / "devin-data")
    env["DEVIN_CONFIG_DIR"] = str(tmp_path / "devin-config")
    data, config = tmp_path / "devin-data", tmp_path / "devin-config"
    (data / "User" / "acp-messages").mkdir(parents=True)
    (config / "User" / "globalStorage").mkdir(parents=True)
    (config / "User" / "globalStorage" / "state.vscdb").touch()

    paths = resolve(env, "linux")

    assert paths.acp_messages_dir == data / "User" / "acp-messages"
    assert paths.state_vscdb == (
        config / "User" / "globalStorage" / "state.vscdb"
    )


# ---------------------------------------------------------------------------
# ecosystem anchor — identity files never follow User/ probing
# ---------------------------------------------------------------------------


def test_ecosystem_anchor_ignores_late_lowercase_user_tree(tmp_path):
    """A ``devin/User`` tree appearing after the fact must not move the
    identity anchor away from canonical ``Devin``."""
    env = _linux_env(tmp_path)

    before = ecosystem_anchor_dir(env, "linux")
    (tmp_path / "xdg-config" / "devin" / "User").mkdir(parents=True)
    after = ecosystem_anchor_dir(env, "linux")

    assert before == after == tmp_path / "xdg-config" / "Devin"
    # config_dir DOES follow User/ — the anchor is deliberately separate.
    assert default_config_dir(env, "linux").name == "devin"


def test_ecosystem_anchor_reads_existing_lowercase_ecosystem(tmp_path):
    """A machine whose ``.devin-ecosystem`` already lives under the
    lowercase root keeps it — identity is never re-anchored."""
    env = _linux_env(tmp_path)
    legacy_eco = tmp_path / "xdg-config" / "devin" / ".devin-ecosystem"
    legacy_eco.mkdir(parents=True)

    assert ecosystem_anchor_dir(env, "linux") == (
        tmp_path / "xdg-config" / "devin"
    )
    assert resolve(env, "linux").ecosystem_dir == legacy_eco


def test_ecosystem_anchor_env_override_wins(tmp_path):
    env = _linux_env(tmp_path)
    env["DEVIN_CONFIG_DIR"] = str(tmp_path / "explicit")

    assert ecosystem_anchor_dir(env, "linux") == tmp_path / "explicit"
