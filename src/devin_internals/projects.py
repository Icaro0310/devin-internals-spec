"""Canonical project identity derived from ``sessions.working_directory``.

The same logical project can appear under slightly different paths
(``~/devin/foo`` vs ``/home/user/devin/foo/``, case differences on
Windows). These helpers give every tool in the ecosystem the same
normalization so sessions, graph nodes, history notes and memories join on
one stable key.

Conventions:

- ``canonical_project_path`` — the expanded, normalized absolute-ish path.
  ``~`` expands against the current user; redundant separators, ``.``
  segments and a trailing slash are removed. On Windows the result is
  case-folded (NTFS is case-insensitive) and uses forward slashes.
- ``canonical_project_key`` — the join key used for graph nodes, index
  entries and cross-tool references: the lowercase basename of the
  canonical path. Two checkouts of the same project in different parents
  intentionally collide — the key identifies the *project*, not the
  checkout. Callers that need checkout granularity keep the path too.
- ``project_display_name`` — the basename without case-folding, for UI.
"""

from __future__ import annotations

import os
import posixpath
import sys

_UNNAMED = "(no-project)"


def _is_windows(platform: str | None) -> bool:
    return (platform or sys.platform).startswith("win")


def canonical_project_path(
    working_directory: str | None, platform: str | None = None
) -> str:
    """Normalized path for one ``working_directory``.

    ``None``/empty maps to ``""`` — callers decide whether that is a valid
    session at all.
    """
    if not working_directory:
        return ""
    raw = os.path.expanduser(working_directory.strip())
    if _is_windows(platform):
        # normalize on POSIX rules after converting separators so the key
        # does not depend on which OS produced the record
        raw = raw.replace("\\", "/")
        norm = posixpath.normpath(raw).casefold()
    else:
        # posixpath, not os.path: a working_directory recorded on Linux
        # must normalize identically when read on a Windows host (or when
        # the caller pins platform="linux" for cross-platform joins)
        norm = posixpath.normpath(raw)
    if norm == ".":
        return ""
    return norm


def canonical_project_key(
    working_directory: str | None, platform: str | None = None
) -> str:
    """Stable join key: lowercase basename of the canonical path."""
    path = canonical_project_path(working_directory, platform)
    if not path:
        return _UNNAMED
    return posixpath.basename(path).lower()


def project_display_name(
    working_directory: str | None, platform: str | None = None
) -> str:
    """Human-facing project name (basename, original case)."""
    path = canonical_project_path(working_directory, platform)
    if not path:
        return _UNNAMED
    return posixpath.basename(path)
