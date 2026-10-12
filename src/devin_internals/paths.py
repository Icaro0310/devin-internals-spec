"""Canonical locations of Devin's local stores and ecosystem bookkeeping.

This module is the single source of truth for *where* Devin keeps its
on-disk state (D-2026-10-08: shared infra extracted into the spec; 11+
packages with vendored, drifted ``paths.py`` copies converge on it).

The convention, verified against a real install (2026-10)::

    platform   data root                                 UI config root
    Linux      $XDG_DATA_HOME/devin                      $XDG_CONFIG_HOME/Devin
               (~/.local/share/devin)                    (~/.config/Devin)
    Windows    %APPDATA%\\devin                          %APPDATA%\\Devin
    macOS      ~/Library/Application Support/devin       ~/Library/Application Support/Devin

Layout::

    <data>/cli/sessions.db                    session metadata + message tree
    <data>/cli/session_locks/                 per-session lock files
    <data>/credentials.toml                   CLI credentials
    <config>/User/acp-messages/*.db           per-session ACP message logs
    <config>/User/globalStorage/state.vscdb   editor/workbench state
    <config>/.devin-ecosystem/                ecosystem bookkeeping
        machine-id, devin-profile.json, hooks.json, scheduled.json,
        plans.jsonl, metrics/

Both roots accept env overrides: ``DEVIN_DATA_DIR`` and ``DEVIN_CONFIG_DIR``.

Known drifts this module resolves (do not reintroduce):

- The macOS and Linux UI config dir is ``Devin``, capitalized — several
  vendored copies fall back to lowercase ``devin``.
- ``.devin-ecosystem/`` anchors under the **Devin config dir** (e.g.
  ``~/.config/Devin/.devin-ecosystem``), never under bare
  ``$XDG_CONFIG_HOME`` — the orchestrator's ``plans.jsonl`` drifted to
  ``$XDG_CONFIG_HOME/.devin-ecosystem/plans.jsonl``.
- On Linux the CLI data root and the UI config root are *different*
  directories; on Windows/macOS they differ only by case and collapse into
  one on case-insensitive filesystems. Fixture-style layouts also keep
  ``User/`` under the data root — :func:`resolve` detects that unified
  layout, same rule ``devin_internals.contract._gui_root`` applies.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

DATA_DIR_ENV = "DEVIN_DATA_DIR"
CONFIG_DIR_ENV = "DEVIN_CONFIG_DIR"
ECOSYSTEM_DIRNAME = ".devin-ecosystem"


def default_data_dir(
    environ: dict[str, str] | None = None, platform: str | None = None
) -> Path:
    """Best-effort location of Devin's session data root.

    ``DEVIN_DATA_DIR`` wins; then the platform default. On Linux a few
    legacy layouts kept ``cli/sessions.db`` under the config or home
    roots, so candidates are probed newest-layout-first and the first one
    holding the store wins; a fresh machine falls back to
    ``$XDG_DATA_HOME/devin``.
    """
    env = os.environ if environ is None else environ
    plat = sys.platform if platform is None else platform
    override = env.get(DATA_DIR_ENV)
    if override:
        return Path(override).expanduser()
    if plat.startswith("win"):
        appdata = env.get("APPDATA")
        if appdata:
            return Path(appdata) / "devin"
        return Path.home() / "AppData" / "Roaming" / "devin"
    if plat == "darwin":
        return Path.home() / "Library" / "Application Support" / "devin"
    candidates = _data_root_candidates(env)
    return next(
        (root for root in candidates if sessions_db_path(root).is_file()),
        candidates[0],
    )


def default_config_dir(
    environ: dict[str, str] | None = None, platform: str | None = None
) -> Path:
    """Best-effort location of Devin Desktop's UI/config stores.

    ``DEVIN_CONFIG_DIR`` wins; then the platform default. On Linux both
    ``Devin`` and ``devin`` exist in the wild — the candidate holding a
    ``User/`` tree wins; a fresh machine falls back to ``Devin``,
    capitalized.

    Identity files must NOT anchor here — a ``User/`` tree appearing
    under the lowercase root later would silently move them. Use
    :func:`ecosystem_anchor_dir` for ``.devin-ecosystem``.
    """
    env = os.environ if environ is None else environ
    plat = sys.platform if platform is None else platform
    override = env.get(CONFIG_DIR_ENV)
    if override:
        return Path(override).expanduser()
    if plat.startswith("win") or plat == "darwin":
        return _platform_config_dir(env, plat)
    candidates = _config_root_candidates(env)
    return next(
        (root for root in candidates if (root / "User").is_dir()),
        candidates[0],
    )


def _platform_config_dir(env: dict[str, str], plat: str) -> Path:
    """Non-Linux config default (Windows/macOS probe nothing)."""
    if plat.startswith("win"):
        appdata = env.get("APPDATA")
        if appdata:
            return Path(appdata) / "Devin"
        return Path.home() / "AppData" / "Roaming" / "Devin"
    return Path.home() / "Library" / "Application Support" / "Devin"


def ecosystem_anchor_dir(
    environ: dict[str, str] | None = None, platform: str | None = None
) -> Path:
    """Directory ``.devin-ecosystem`` anchors under.

    ``DEVIN_CONFIG_DIR`` wins; then the platform default. On Linux the
    first config-root candidate already holding ``.devin-ecosystem``
    wins — identity files (``machine-id``, ``devin-profile.json``) must
    never silently move just because a ``User/`` tree appeared under
    the other root — and a fresh machine falls back to the canonical
    capitalized ``Devin``. Unlike :func:`default_config_dir` this never
    follows ``User/`` presence, so the anchor is stable across
    GUI-store drift.
    """
    env = os.environ if environ is None else environ
    plat = sys.platform if platform is None else platform
    override = env.get(CONFIG_DIR_ENV)
    if override:
        return Path(override).expanduser()
    if plat.startswith("win") or plat == "darwin":
        return _platform_config_dir(env, plat)
    candidates = _config_root_candidates(env)
    return next(
        (
            root
            for root in candidates
            if (root / ECOSYSTEM_DIRNAME).is_dir()
        ),
        candidates[0],
    )


def _data_root_candidates(env: dict[str, str]) -> list[Path]:
    """Linux data-root candidates, newest layout first."""
    data_home = Path(env.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    config_home = Path(env.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return [data_home / "devin", config_home / "devin", Path.home() / "devin"]


def _config_root_candidates(env: dict[str, str]) -> list[Path]:
    """Linux config-root candidates — canonical ``Devin`` first."""
    config_home = Path(env.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return [config_home / "Devin", config_home / "devin"]


# ---------------------------------------------------------------------------
# store-relative helpers
# ---------------------------------------------------------------------------


def sessions_db_path(data_root: Path) -> Path:
    return Path(data_root) / "cli" / "sessions.db"


def session_locks_dir_path(data_root: Path) -> Path:
    return Path(data_root) / "cli" / "session_locks"


def credentials_toml_path(data_root: Path) -> Path:
    return Path(data_root) / "credentials.toml"


def acp_messages_dir_path(config_root: Path) -> Path:
    return Path(config_root) / "User" / "acp-messages"


def state_vscdb_path(config_root: Path) -> Path:
    return Path(config_root) / "User" / "globalStorage" / "state.vscdb"


def ecosystem_dir_path(config_root: Path) -> Path:
    """``<config>/.devin-ecosystem`` — always anchored under the Devin
    config dir, never under bare ``$XDG_CONFIG_HOME``."""
    return Path(config_root) / ECOSYSTEM_DIRNAME


def _gui_root(data_dir: Path, config_dir: Path, store: str) -> Path:
    """Locate the ``User/`` tree holding ``store``.

    Fixture-style and unified layouts keep ``User/`` under the data root;
    real Linux installs split stores across ``~/.local/share/devin``
    (data) and ``~/.config/Devin`` (UI config). When both roots hold a
    ``User/`` directory, the one containing the requested store wins —
    an empty ``User/`` under the data root must not hide real GUI
    stores under the config root. Same rule ``contract._gui_root``
    applies to a caller-supplied data dir.
    """
    if (Path(data_dir) / "User" / store).exists():
        return Path(data_dir)
    if (Path(config_dir) / "User" / store).exists():
        return Path(config_dir)
    if (Path(data_dir) / "User").is_dir():
        return Path(data_dir)
    return Path(config_dir)


# ---------------------------------------------------------------------------
# resolved view
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DevinPaths:
    """Everything a consumer needs to know about where stores live."""

    data_dir: Path
    """CLI session-data root (``cli/sessions.db``, ``credentials.toml``)."""
    config_dir: Path
    """Desktop UI/config root — anchors ``User/`` and ``.devin-ecosystem/``."""
    sessions_db: Path
    session_locks_dir: Path
    credentials_toml: Path
    acp_messages_dir: Path
    state_vscdb: Path
    ecosystem_dir: Path
    """``<config>/.devin-ecosystem`` — machine-id, profile, hooks,
    scheduled jobs, plans, metrics. Anchored via
    :func:`ecosystem_anchor_dir`, which does not follow ``User/``
    presence, so identity files never silently move."""


def resolve(
    environ: dict[str, str] | None = None, platform: str | None = None
) -> DevinPaths:
    """Resolve every canonical location for this machine/user.

    Honors ``DEVIN_DATA_DIR``/``DEVIN_CONFIG_DIR`` and the platform
    (``sys.platform``; both injectable for tests). Probing is
    best-effort: only whether a directory/file exists is inspected —
    nothing is created.
    """
    env = os.environ if environ is None else environ
    plat = sys.platform if platform is None else platform
    data_dir = default_data_dir(env, plat)
    config_dir = default_config_dir(env, plat)
    acp_root = _gui_root(data_dir, config_dir, "acp-messages")
    state_root = _gui_root(
        data_dir, config_dir, str(Path("globalStorage") / "state.vscdb")
    )
    return DevinPaths(
        data_dir=data_dir,
        config_dir=config_dir,
        sessions_db=sessions_db_path(data_dir),
        session_locks_dir=session_locks_dir_path(data_dir),
        credentials_toml=credentials_toml_path(data_dir),
        acp_messages_dir=acp_messages_dir_path(acp_root),
        state_vscdb=state_vscdb_path(state_root),
        ecosystem_dir=ecosystem_dir_path(ecosystem_anchor_dir(env, plat)),
    )


# ---------------------------------------------------------------------------
# candidate-order helpers — files that may live under data OR config roots
# ---------------------------------------------------------------------------


def _dedup(paths: Iterable[Path]) -> list[Path]:
    """Drop exact duplicates, keep order."""
    return list(dict.fromkeys(paths))


def _legacy_cli_config_root(config_dir: Path) -> Path:
    """The lowercase sibling of the UI config root.

    Split Linux installs kept CLI stores under
    ``$XDG_CONFIG_HOME/devin`` while the desktop writes its ``User/``
    tree under ``$XDG_CONFIG_HOME/Devin`` — the UI root passed as
    ``config_dir`` is not an alias for that legacy CLI root. When
    ``config_dir`` is already the lowercase root (or an explicit
    override), dedup or a nonexistent path keeps the candidate list
    honest.
    """
    return Path(config_dir).parent / "devin"


def sessions_db_candidates(
    data_dir: str | Path, config_dir: str | Path
) -> list[Path]:
    """``cli/sessions.db`` — data root is canonical; the config root and
    its lowercase sibling are legacy fallbacks (split Linux installs
    kept it under ``$XDG_CONFIG_HOME/devin``, not under the ``Devin``
    UI root)."""
    return _dedup(
        [
            sessions_db_path(Path(data_dir)),
            sessions_db_path(Path(config_dir)),
            sessions_db_path(_legacy_cli_config_root(Path(config_dir))),
        ]
    )


def session_locks_dir_candidates(
    data_dir: str | Path, config_dir: str | Path
) -> list[Path]:
    """``cli/session_locks/`` — same data-first order and lowercase-sibling
    legacy fallback as ``sessions.db`` (locks live beside it)."""
    return _dedup(
        [
            session_locks_dir_path(Path(data_dir)),
            session_locks_dir_path(Path(config_dir)),
            session_locks_dir_path(_legacy_cli_config_root(Path(config_dir))),
        ]
    )


def credentials_toml_candidates(
    data_dir: str | Path, config_dir: str | Path
) -> list[Path]:
    """``credentials.toml`` — data root is canonical; unified layouts keep
    it beside the UI stores under the config root."""
    return _dedup(
        [
            credentials_toml_path(Path(data_dir)),
            credentials_toml_path(Path(config_dir)),
        ]
    )


def acp_messages_dir_candidates(
    data_dir: str | Path, config_dir: str | Path
) -> list[Path]:
    """``User/acp-messages/`` — config root is canonical; fixture/unified
    layouts keep ``User/`` under the data root."""
    return _dedup(
        [
            acp_messages_dir_path(Path(config_dir)),
            acp_messages_dir_path(Path(data_dir)),
        ]
    )


def state_vscdb_candidates(
    data_dir: str | Path, config_dir: str | Path
) -> list[Path]:
    """``User/globalStorage/state.vscdb`` — config root is canonical;
    fixture/unified layouts keep it under the data root."""
    return _dedup(
        [
            state_vscdb_path(Path(config_dir)),
            state_vscdb_path(Path(data_dir)),
        ]
    )


def first_existing(candidates: Iterable[str | Path]) -> Path | None:
    """First candidate that exists on disk, or ``None``."""
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return path
    return None
