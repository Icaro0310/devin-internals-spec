"""Shared incrementality cursor — one pattern, many surfaces.

Every incremental mechanism in the ecosystem reduces to a cursor plus
an envelope (spec: ``devin-powerups/docs/incrementality.md``). This
module implements the third storage shape — a small JSON state file —
used by learning extract, sweeps, digests and other watermarks. The
other two shapes (artifact-embedded markers, state tables inside the
produced store) stay where they are; this module does not replace
them.

Contract:

- JSON object only, flat keys — the file is an ops artifact, not a
  schema boundary.
- ``commit()`` is the only write and is atomic (tmp + ``os.replace``);
  call it *after* the work so a crash re-scans instead of skipping.
- Missing or corrupt state → empty state (fail-open).
- The anchor dir defaults to ``<cwd>/.devin`` and is overridable per
  cursor (``DEVIN_CURSOR_DIR`` env or an explicit ``dir``).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

CURSOR_DIR_ENV = "DEVIN_CURSOR_DIR"


class Cursor:
    """A named incremental cursor stored as ``<dir>/<name>-state.json``.

    Reads are lazy: the file is loaded on first access. ``set()``
    mutates an in-memory copy; nothing is durable until ``commit()``.
    """

    def __init__(
        self,
        name: str,
        dir: str | Path | None = None,
        environ: dict[str, str] | None = None,
    ) -> None:
        if not name or "/" in name or name.startswith("."):
            raise ValueError(f"invalid cursor name {name!r}")
        self.name = name
        env = os.environ if environ is None else environ
        if dir is None:
            anchor = env.get(CURSOR_DIR_ENV)
            dir = Path(anchor) if anchor else Path.cwd() / ".devin"
        self.path = Path(dir) / f"{name}-state.json"
        self._state: dict | None = None

    def _load(self) -> dict:
        if self._state is None:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self._state = data if isinstance(data, dict) else {}
            except (OSError, json.JSONDecodeError):
                self._state = {}
        return self._state

    def get(self, key: str, default=None):
        return self._load().get(key, default)

    def set(self, key: str, value) -> None:
        self._load()[key] = value

    def as_dict(self) -> dict:
        return dict(self._load())

    def commit(self) -> Path:
        """Durably write the cursor (atomic tmp+replace)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=self.path.parent, prefix=self.path.name, suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._load(), fh, ensure_ascii=False, indent=1)
                fh.write("\n")
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return self.path

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        state = "loaded" if self._state is not None else "unread"
        return f"Cursor({self.name!r}, path={self.path}, {state})"
