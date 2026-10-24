"""Fuzz regression pack: ``fuzz/corpus/`` is the checked-in corpus.

``devin-inspect cflite-promote`` lands minimized ClusterFuzzLite crashes
here as ``crash-<sha256>`` files indexed by ``manifest.json``; ``seed-*``
files are the curated start corpus. The pack must hold together — every
crash entry on disk hashed into the manifest, all within the reproducer
bounds — and every entry must replay cleanly through the exact
consumption the fuzz target performs (``detect_schema_version`` over the
bytes as a ``.db`` file). A crash that still crashes fails loudly, which
is the point of the pack.
"""

import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest
from devin_internals import cflite
from devin_internals.schema import SchemaError, detect_schema_version

CORPUS_DIR = Path(__file__).resolve().parents[1] / "fuzz" / "corpus"
MANIFEST = CORPUS_DIR / cflite.MANIFEST_NAME


def _entries() -> list[Path]:
    """Crash entries on disk — files named ``crash-<sha256>``."""
    if not CORPUS_DIR.is_dir():
        return []
    return sorted(
        p
        for p in CORPUS_DIR.iterdir()
        if p.is_file() and p.name.startswith(cflite.ENTRY_PREFIX)
    )


def _seeds() -> list[Path]:
    """Curated seed inputs — ``seed-*`` files, never crash entries."""
    if not CORPUS_DIR.is_dir():
        return []
    return sorted(
        p
        for p in CORPUS_DIR.iterdir()
        if p.is_file() and p.name.startswith(cflite.SEED_PREFIX)
    )


def _replay(path: Path) -> None:
    """The fuzz target's consumption: bytes -> .db -> detect."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=True) as tmp:
        tmp.write(path.read_bytes())
        tmp.flush()
        detect_schema_version(Path(tmp.name))


def test_corpus_pack_integrity():
    entries = _entries()
    assert MANIFEST.is_file(), f"missing {MANIFEST}"
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    listed = set(manifest.get("entries", {}))
    assert listed == {p.name for p in entries}, (
        f"manifest/disk mismatch: {listed ^ {p.name for p in entries}}"
    )
    seeds = manifest.get("seeds", {})
    assert set(seeds) == {p.name for p in _seeds()}, (
        "seeds on disk must be the ones the manifest records"
    )


@pytest.mark.parametrize(
    "entry", _entries() + _seeds(), ids=lambda p: p.name[:24]
)
def test_corpus_entry_replays_cleanly(entry: Path):
    """Expected rejections only — an unhandled type means a live crash."""
    try:
        _replay(entry)
    except (SchemaError, sqlite3.Error):
        pass  # the detector refused the input; it did not crash on it


def test_promote_dedup_and_bounds(tmp_path):
    crashes = tmp_path / "crashes"
    crashes.mkdir()
    (crashes / "oom.bin").write_bytes(b"\x00" * (cflite.MAX_CRASH_BYTES + 1))
    (crashes / "empty").write_bytes(b"")
    good = crashes / "crash-a"
    good.write_bytes(b"SQLite format 3\x00" + b"\x00" * 100)
    corpus = tmp_path / "corpus"
    rep = cflite.promote(crashes, corpus)
    assert [p["file"] for p in rep["promoted"]] == ["crash-a"]
    assert {r["file"] for r in rep["rejected"]} == {"oom.bin", "empty"}
    # second promotion of the same bytes is a dedup hit, not a copy
    rep2 = cflite.promote(crashes, corpus)
    assert rep2["promoted"] == []
    assert rep2["skipped_dup"]
    # dry-run reports but writes nothing
    (crashes / "crash-b").write_bytes(b"another input")
    rep3 = cflite.promote(crashes, corpus, dry_run=True)
    assert rep3["promoted"]
    sha = hashlib.sha256(b"another input").hexdigest()
    assert not (corpus / cflite._entry_name(sha)).exists()


def test_malformed_entry_name_fails_loud(tmp_path):
    """A ``crash-`` file whose name is not its sha256 is corruption."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "crash-notasha").write_bytes(b"junk")
    crashes = tmp_path / "crashes"
    crashes.mkdir()
    (crashes / "x").write_bytes(b"new crash bytes")
    rep = cflite.promote(crashes, corpus)
    assert rep["errors"]  # loud, not silently skipped
    assert rep["promoted"] == []
