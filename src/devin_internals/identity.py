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
  ``<ecosystem>/machine-id`` (mode 0600, published on first use via
  exclusive create — concurrent losers adopt the winner's value; never
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
import time
from pathlib import Path

from devin_internals.paths import ECOSYSTEM_DIRNAME, ecosystem_anchor_dir

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
    return ecosystem_anchor_dir(env, plat) / ECOSYSTEM_DIRNAME


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
    except FileNotFoundError:
        existing = ""
    except UnicodeDecodeError:
        existing = ""  # corrupt file — the publish path reclaims it
    # Any other OSError (permissions, I/O) propagates: an existing but
    # unreadable id must never be silently replaced.
    if existing:
        return existing
    return _publish_machine_id(path)


def _publish_machine_id(path: Path) -> str:
    """Create ``path`` exactly once and return the persisted id.

    ``O_EXCL`` creation at mode ``0600`` serializes first use across
    processes: the loser of a creation race reads back the winner's
    value instead of splitting provenance, and the id is never
    world-readable, not even between create and ``fchmod``. An empty or
    undecodable file left behind (crashed publisher, corrupt copy) is
    reclaimed after a short wait.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    for _attempt in range(5):
        value = secrets.token_hex(8)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            winner = _wait_for_published_id(path)
            if winner:
                return winner
            try:
                path.unlink()  # stale/corrupt — reclaim and retry
            except OSError:
                pass
            continue
        try:
            fchmod = getattr(os, "fchmod", None)  # Unix-only
            if fchmod is not None:
                try:
                    fchmod(fd, 0o600)
                except OSError:  # filesystems without POSIX modes
                    pass
            os.write(fd, f"{value}\n".encode("ascii"))
        finally:
            os.close(fd)
        return value
    winner = _wait_for_published_id(path)
    if winner:
        return winner
    raise OSError(f"could not establish a stable machine-id at {path}")


def _wait_for_published_id(path: Path) -> str:
    """Read the race winner's id; ``""`` while the file is still empty
    or undecodable.

    Missing is fine (the caller retries the create); other read errors
    propagate — an existing but unreadable id is never replaced.
    """
    for _ in range(50):  # ~1s bound — a publish takes microseconds
        try:
            winner = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return ""
        except UnicodeDecodeError:
            winner = ""
        if winner:
            return winner
        time.sleep(0.02)
    return ""


def _profile_from_file(path: Path) -> str | None:
    """Profile stored in ``path``; ``None`` only when the file is absent.

    A present but unreadable, corrupt or unrecognized file fails closed
    to the default — it must not silently fall through to a less strict
    legacy value.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):  # incl. JSONDecodeError, UnicodeDecodeError
        return DEFAULT_PROFILE
    raw = data.get("profile") if isinstance(data, dict) else data
    raw = str(raw or "").strip().lower()
    return raw if raw in PROFILES else DEFAULT_PROFILE


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
