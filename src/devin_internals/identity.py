"""Opaque machine identity + profile for ecosystem provenance metadata.

Artifacts written by devin-* tools carry ``machine_id`` + ``profile`` so
output produced on different machines (e.g. personal vs corporate) can be
told apart — without leaking hostnames, usernames or MAC addresses.

Both files live under ``<devin-config-dir>/.devin-ecosystem/`` — the
canonical anchor resolved by :mod:`devin_internals.paths` (e.g.
``~/.config/Devin/.devin-ecosystem`` on Linux), shared by every tool on
the machine.

Resolution order:

- ``machine_id``: the ``DEVIN_MACHINE_ID`` env var wins; otherwise a
  random ``secrets.token_hex(8)`` persisted at
  ``<ecosystem>/machine-id`` (mode 0600, created on first use, never
  regenerated). Never derived from hostname, username or hardware ids.
- ``profile``: the ``DEVIN_ECOSYSTEM_PROFILE`` env var
  (``"corporate"`` | ``"personal"``) — a set-but-unrecognized value fails
  closed to ``"corporate"``; otherwise ``devin-profile.json`` (canonical
  ``<ecosystem>/devin-profile.json`` first, then the legacy
  ``<config>/devin-profile.json`` drifted copies wrote); otherwise
  ``"corporate"`` — fail-closed.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
from pathlib import Path

from devin_internals.paths import ECOSYSTEM_DIRNAME, default_config_dir

MACHINE_ID_ENV = "DEVIN_MACHINE_ID"
PROFILE_ENV = "DEVIN_ECOSYSTEM_PROFILE"
MACHINE_ID_FILENAME = "machine-id"
PROFILE_FILENAME = "devin-profile.json"
PROFILES = ("corporate", "personal")
DEFAULT_PROFILE = "corporate"  # fail-closed


def _ecosystem_dir(
    env: dict[str, str],
    plat: str,
    ecosystem_dir: str | Path | None,
) -> Path:
    """Explicit dir wins; otherwise the canonical
    ``<devin-config-dir>/.devin-ecosystem``."""
    if ecosystem_dir is not None:
        return Path(ecosystem_dir).expanduser()
    return default_config_dir(env, plat) / ECOSYSTEM_DIRNAME


def machine_id_path(
    environ: dict[str, str] | None = None,
    platform: str | None = None,
    *,
    ecosystem_dir: str | Path | None = None,
) -> Path:
    """Where the machine-id file lives (does not create it)."""
    env = os.environ if environ is None else environ
    plat = sys.platform if platform is None else platform
    return _ecosystem_dir(env, plat, ecosystem_dir) / MACHINE_ID_FILENAME


def profile_path_candidates(
    environ: dict[str, str] | None = None,
    platform: str | None = None,
    *,
    ecosystem_dir: str | Path | None = None,
) -> list[Path]:
    """``devin-profile.json`` candidates, canonical first.

    ``<ecosystem>/devin-profile.json`` is canonical; the parent entry
    covers the ``<config>/devin-profile.json`` location drifted copies
    wrote before the convention converged.
    """
    env = os.environ if environ is None else environ
    plat = sys.platform if platform is None else platform
    eco = _ecosystem_dir(env, plat, ecosystem_dir)
    return [eco / PROFILE_FILENAME, eco.parent / PROFILE_FILENAME]


def machine_id(
    environ: dict[str, str] | None = None,
    platform: str | None = None,
    *,
    ecosystem_dir: str | Path | None = None,
) -> str:
    """Stable opaque id for this machine (16 hex chars).

    Created once and persisted — the same value is returned on every
    subsequent call; it is never regenerated.
    """
    env = os.environ if environ is None else environ
    plat = sys.platform if platform is None else platform
    override = (env.get(MACHINE_ID_ENV) or "").strip()
    if override:
        return override
    path = _ecosystem_dir(env, plat, ecosystem_dir) / MACHINE_ID_FILENAME
    try:
        existing = path.read_text(encoding="utf-8").strip()
    except OSError:
        existing = ""
    if existing:
        return existing
    value = secrets.token_hex(8)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:  # filesystems without POSIX modes
        pass
    return value


def _profile_from_file(path: Path) -> str | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    raw = data.get("profile") if isinstance(data, dict) else data
    raw = str(raw or "").strip().lower()
    return raw if raw in PROFILES else None


def profile(
    environ: dict[str, str] | None = None,
    platform: str | None = None,
    *,
    ecosystem_dir: str | Path | None = None,
) -> str:
    """``"corporate"`` | ``"personal"`` — unknown values fail closed."""
    env = os.environ if environ is None else environ
    plat = sys.platform if platform is None else platform
    raw = (env.get(PROFILE_ENV) or "").strip().lower()
    if raw in PROFILES:
        return raw
    if raw:
        return DEFAULT_PROFILE  # set but unrecognized — fail closed
    for candidate in profile_path_candidates(env, plat, ecosystem_dir=ecosystem_dir):
        value = _profile_from_file(candidate)
        if value is not None:
            return value
    return DEFAULT_PROFILE


def provenance(
    environ: dict[str, str] | None = None,
    platform: str | None = None,
    *,
    ecosystem_dir: str | Path | None = None,
) -> dict[str, str]:
    """``{"machine_id": ..., "profile": ...}`` for embedding in outputs."""
    return {
        "machine_id": machine_id(environ, platform, ecosystem_dir=ecosystem_dir),
        "profile": profile(environ, platform, ecosystem_dir=ecosystem_dir),
    }
