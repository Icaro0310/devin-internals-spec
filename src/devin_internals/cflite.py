"""ClusterFuzzLite crash promotion — minimized crashes → regression corpus.

Ported from devin-redact's ``cflite.py`` (same contract, minus the
secret-scan gate: that engine lives in devin-redact, and the inputs here
are synthetic CI artifacts — the fuzzer never sees real credentials).

The ``fuzz`` workflow (``.github/workflows/cflite.yml``) runs the atheris
target (``fuzz/fuzz_schema.py``) in ``code-change`` mode: when a run finds
a crash, ClusterFuzzLite minimizes it and uploads the testcase as a
workflow-run artifact. ``promote()`` copies those artifacts into the
checked-in regression corpus (``fuzz/corpus/``) so every crash becomes a
permanent replay input for ``tests/test_fuzz_corpus.py``.

Corpus contract:

- one file per crash, named ``crash-<sha256-of-contents>`` — the name is
  the dedup key, so byte-identical artifacts collapse automatically;
- ``seed-*`` files are the curated start corpus the fuzzer replays —
  they are left untouched by promotion and never treated as crashes;
- ``manifest.json`` records provenance (source artifact name, workflow
  run id, byte size, promotion timestamp);
- entries are binary-safe fuzzer inputs, so validation is bounds-only:
  a real reproducer is a regular file, non-empty, and within
  ``MAX_CRASH_BYTES`` — anything failing the bounds is *rejected* and
  reported in the ``rejected`` list, never silently skipped.

Artifact acquisition is deliberately two-path: ``--crashes-dir`` reads an
already-unpacked dir (the offline/testable path), while ``--run-id``
fetches a run's artifacts through ``gh run download`` — each artifact
lands in its own subdirectory, so candidate discovery is recursive.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import __version__

#: Environment override for the corpus location; ``--corpus-dir`` wins.
CORPUS_ENV = "DEVIN_INTERNALS_CFLITE_CORPUS"
#: Provenance index living inside the corpus dir.
MANIFEST_NAME = "manifest.json"
#: Every promoted crash is stored as ``crash-<sha256>``.
ENTRY_PREFIX = "crash-"
#: Curated seeds replayed by the fuzzer — never crash entries.
SEED_PREFIX = "seed-"
#: Upper bound for a reproducer. The harness caps its byte consumption at
#: 8192 via the provider; 64 KiB is generous — anything bigger is a
#: mis-exported artifact, not a minimized crash.
MAX_CRASH_BYTES = 1 << 16
_GH = "gh"


class CfliteError(RuntimeError):
    """Hard failure locating or downloading crash artifacts."""


def _package_root() -> Path | None:
    """The repo checkout root, when running from one."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "fuzz" / "fuzz_schema.py").is_file():
            return parent
    return None


def default_corpus_dir(environ: dict[str, str] | None = None) -> Path:
    """``<repo>/fuzz/corpus`` — the checked-in regression pack.

    ``DEVIN_INTERNALS_CFLITE_CORPUS`` wins; outside a source checkout
    (wheel install) the fallback is ``./fuzz/corpus`` under the cwd.
    """
    env = os.environ if environ is None else environ
    override = env.get(CORPUS_ENV)
    if override:
        return Path(override)
    root = _package_root()
    return (root if root is not None else Path.cwd()) / "fuzz" / "corpus"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _entry_name(sha: str) -> str:
    return f"{ENTRY_PREFIX}{sha}"


def _iter_candidates(crashes_dir: Path) -> list[Path]:
    """Every non-directory path under ``crashes_dir``, recursively, in
    deterministic order. Non-regular files stay in the list — they are
    rejected by ``_validate`` rather than silently skipped."""
    return sorted(p for p in crashes_dir.rglob("*") if not p.is_dir())


def _validate(path: Path, max_bytes: int) -> str | None:
    """Rejection reason, or ``None`` when the file passes the bounds."""
    try:
        st = path.stat()
    except OSError as exc:
        return f"unreadable: {exc}"
    if not path.is_file():
        return "not a regular file"
    if st.st_size == 0:
        return "empty file — not a reproducer"
    if st.st_size > max_bytes:
        return f"{st.st_size} bytes exceeds the {max_bytes}-byte cap"
    return None


_ENTRY_RE = re.compile(rf"^{ENTRY_PREFIX}[0-9a-f]{{64}}$")


def _corpus_hashes(corpus_dir: Path, errors: list[dict]) -> dict[str, str]:
    """sha256 → filename for every *validated crash entry* on disk.

    Only ``crash-<sha256>`` files whose name matches their contents
    count — a stray seed/note file with identical bytes must not
    satisfy dedup, or the crash never lands as a replayable entry.
    A misnamed ``crash-*`` file is corrupt and fails loud.
    """
    hashes: dict[str, str] = {}
    if not corpus_dir.is_dir():
        return hashes
    for p in sorted(corpus_dir.iterdir()):
        if not _ENTRY_RE.match(p.name):
            # a ``crash-`` name is the corpus contract — anything else
            # starting with the prefix is a malformed entry the
            # integrity test would reject, not a stray file to ignore
            if p.name.startswith(ENTRY_PREFIX):
                errors.append(
                    {
                        "file": str(p),
                        "error": "malformed crash entry name — "
                        f"expected {ENTRY_PREFIX}<sha256>",
                    }
                )
            continue
        if not p.is_file():
            errors.append(
                {
                    "file": str(p),
                    "error": "crash entry is not a regular file",
                }
            )
            continue
        # the same bounds as promoted candidates — an oversized or
        # empty entry is corrupt, whatever its name-hash agreement
        reason = _validate(p, MAX_CRASH_BYTES)
        if reason:
            errors.append(
                {"file": str(p), "error": f"corrupt entry: {reason}"}
            )
            continue
        try:
            sha = _sha256(p.read_bytes())
        except OSError as exc:
            errors.append({"file": str(p), "error": f"unreadable: {exc}"})
            continue
        if p.name != _entry_name(sha):
            errors.append(
                {
                    "file": str(p),
                    "error": "name does not match contents — corrupt entry",
                }
            )
            continue
        hashes.setdefault(sha, p.name)
    return hashes


def _load_manifest(corpus_dir: Path) -> tuple[dict, str | None]:
    """``(manifest, error)`` — a corrupt manifest fails loud and is never
    clobbered: ``promote`` reports the error and leaves the file alone."""
    mpath = corpus_dir / MANIFEST_NAME
    if not mpath.is_file():
        return (
            {
                "tool": "devin-internals",
                "version": __version__,
                "schema": 1,
                "entries": {},
            },
            None,
        )
    try:
        data = json.loads(mpath.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {}, f"unreadable {MANIFEST_NAME}: {exc}"
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, dict):
        return {}, f"malformed {MANIFEST_NAME}: missing 'entries' object"
    return data, None


def download_run_artifacts(
    run_id: str | int, dest_dir: Path, names: tuple[str, ...] | list[str] = ()
) -> None:
    """Fetch a workflow run's artifacts into ``dest_dir`` via ``gh``.

    ``gh run download`` unpacks each artifact into ``dest/<name>/`` (or
    directly into ``dest/`` when ``--name`` selects a single one) —
    ``promote`` discovers candidates recursively, so either layout works.
    """
    cmd = [_GH, "run", "download", str(run_id), "--dir", str(dest_dir)]
    for name in names:
        cmd += ["--name", name]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise CfliteError(f"cannot run gh: {exc}") from exc
    if proc.returncode != 0:
        raise CfliteError(
            f"gh run download {run_id} failed: {proc.stderr.strip()}"
        )


def promote(
    crashes_dir: Path,
    corpus_dir: Path | None = None,
    *,
    max_bytes: int = MAX_CRASH_BYTES,
    run_id: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Copy validated crash artifacts into the checked-in corpus.

    Returns a report dict: ``promoted``/``skipped_dup``/``rejected``/
    ``errors`` lists plus the corpus path. Nothing is written under
    ``dry_run`` — the report is the diff that would apply.
    """
    corpus_dir = corpus_dir or default_corpus_dir()
    report: dict = {
        "corpus_dir": str(corpus_dir),
        "promoted": [],
        "skipped_dup": [],
        "rejected": [],
        "errors": [],
    }
    manifest, merr = _load_manifest(corpus_dir)
    if merr:
        report["errors"].append(merr)
        return report
    existing = _corpus_hashes(corpus_dir, report["errors"])
    if report["errors"]:
        return report

    for cand in _iter_candidates(crashes_dir):
        reason = _validate(cand, max_bytes)
        if reason:
            report["rejected"].append(
                {"file": cand.name, "error": reason})
            continue
        data = cand.read_bytes()
        sha = _sha256(data)
        if sha in existing:
            report["skipped_dup"].append(
                {"file": cand.name, "sha256": sha,
                 "as": existing[sha]})
            continue
        entry = _entry_name(sha)
        report["promoted"].append(
            {
                "file": cand.name,
                "as": entry,
                "sha256": sha,
                "bytes": len(data),
            }
        )
        if not dry_run:
            corpus_dir.mkdir(parents=True, exist_ok=True)
            (corpus_dir / entry).write_bytes(data)
            manifest["entries"][entry] = {
                "sha256": sha,
                "bytes": len(data),
                "source_file": cand.name,
                "run_id": run_id,
                "promoted_at": datetime.now(timezone.utc).isoformat(
                    timespec="seconds"),
            }
        existing[sha] = entry

    if report["promoted"] and not dry_run:
        corpus_dir.mkdir(parents=True, exist_ok=True)
        (corpus_dir / MANIFEST_NAME).write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return report
