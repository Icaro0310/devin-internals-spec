"""Packaged-corpus access tests.

Both corpora ship inside the wheel under ``devin_internals/corpus/`` so
downstream repos (qa-pack, doctor) stop vendoring byte-copies that drift.
These tests pin the ``corpus_access`` contract — ``corpus_root`` resolves,
``materialize_corpus`` writes a real tree — and the anti-drift invariant:
the packaged bytes must equal the committed ``fixtures/`` bytes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from devin_internals.corpus_access import (
    CORPORA,
    corpus_root,
    materialize_corpus,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "fixtures"
PACKAGED = REPO_ROOT / "src" / "devin_internals" / "corpus"


def _file_listing(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_corpus_root_resolves():
    root = corpus_root()
    assert root.is_dir()
    assert sorted(c.name for c in root.iterdir()) == sorted(CORPORA)
    for name in CORPORA:
        assert corpus_root(name).is_dir()


def test_unknown_corpus_rejected(tmp_path):
    with pytest.raises(ValueError, match="unknown corpus"):
        corpus_root("nope")
    # path-shaped names are rejected by the same closed set
    for bad in ("..", "../fixtures", "session-corpus/x"):
        with pytest.raises(ValueError):
            corpus_root(bad)
        with pytest.raises(ValueError):
            materialize_corpus(tmp_path / "x", name=bad)


@pytest.mark.parametrize("name", CORPORA)
def test_materialize_corpus_matches_fixtures(tmp_path, name):
    dest = tmp_path / name
    out = materialize_corpus(dest, name=name)
    assert out == dest
    assert _file_listing(out) == _file_listing(FIXTURES / name)


def test_materialized_evidence_manifest_parses(tmp_path):
    dest = materialize_corpus(tmp_path / "corpus")
    evidence = json.loads((dest / "evidence-manifest.json").read_text())
    committed = json.loads(
        (FIXTURES / "session-corpus" / "evidence-manifest.json").read_text()
    )
    assert evidence["version"] == 1
    assert evidence == committed
    manifest = json.loads((dest / "manifest.json").read_text())
    assert manifest["version"] == 1
    assert [f["surface"] for f in manifest["fixtures"]] == [
        "copilot-cli",
        "codex-cli",
        "vscode-chat",
    ]


def test_materialize_refuses_nonempty_dest(tmp_path):
    dest = tmp_path / "occupied"
    dest.mkdir()
    (dest / "file.txt").write_text("x")
    with pytest.raises(FileExistsError):
        materialize_corpus(dest)


@pytest.mark.parametrize("name", CORPORA)
def test_packaged_corpus_in_sync_with_fixtures(name):
    """Anti-drift guard: ``src/devin_internals/corpus/<name>/`` — what the
    wheel ships — must stay byte-identical to ``fixtures/<name>/``, the
    committed source of truth. Both sides are the same checkout's bytes,
    so the comparison is exact (the corpora's own .gitattributes keeps
    them LF-canonical even under core.autocrlf)."""
    assert _file_listing(PACKAGED / name) == _file_listing(FIXTURES / name)
