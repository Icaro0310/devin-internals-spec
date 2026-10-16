"""Materialize the session-surface fixture corpus (docs/SESSION-SURFACES.md §7).

``build_session_corpus(root)`` writes deterministic fixture stores for the
three non-Devin surfaces — ``copilot/`` (§6.3), ``codex/`` (§6.4),
``vscode-chat/`` (§6.5) — plus ``manifest.json`` declaring the canonical
fields both consumers (TypeScript ``agent-sessions`` and the Python
``devin-search`` collectors) must produce per fixture, and
``evidence-manifest.json`` (docs/SESSION-EVIDENCE.md §8) declaring the
auditable content layer — claims, tool-call kinds, message roles — an
evidence extractor must produce per session. The committed copy at
``fixtures/session-corpus/`` is the vendored artifact other repos copy.

The ``expect`` blocks are derived **by hand** from the spec, not by running a
parser:

- §4 canonical id: ``id_present`` is true only when a stable workspace
  identity exists (native id + workspace hash); flat copilot files carry no
  workspace.yaml and global vscode sessions have no workspace dir → null.
- §5 ended_at chain: ``session.shutdown`` / ``task_complete`` / a completed
  last request are explicit closes (ended_at, no warning); stale activity
  with no marker is an inferred close (ended_at + mandatory
  ``no-end-marker``); ``task_started`` without ``task_complete`` is
  ``session-open`` (ended_at null).
- §6 warning codes used here: ``no-end-marker``, ``session-open``,
  ``unknown-workspace``, ``truncated-tail``, ``duplicates``.

The ``expected_*`` evidence blocks are likewise hand-derived: which claims
the synthetic message text makes (``kind``), what the recorded tool calls
say about them (``verdict``), and which normalized tool-call kinds and
message roles an extractor can deterministically pull.

Nothing content-shaped (message text, titles, real-looking paths) ever
reaches either manifest — native ids, ``/fixture/workspace/*`` seeds and
vocabulary-level assertions only.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from devin_internals import fixtures
from devin_internals.fixtures import DEFAULT_SEED, ms_to_iso

# Closed allowlist of warning codes the manifest may declare — every code is
# named in SESSION-SURFACES §4/§5/§6. Tests enforce that generated and
# hand-written expectations never leave this set.
ALLOWED_WARNING_CODES = frozenset(
    {
        "unknown-workspace",
        "cross-workspace-duplicate",
        "duplicates",
        "session-open",
        "no-end-marker",
        "partial-parse",
        "truncated-tail",
    }
)

# §5 close semantics per fixture session, hand-derived from the spec:
#   "explicit" → a close marker exists; ended_at = its timestamp, no warning
#   "inferred" → stale activity, no marker; ended_at = last activity,
#                `no-end-marker` mandatory (§5.3)
#   "open"     → task started, not completed; ended_at = null (§6.4)
_EXPECT: dict[tuple[str, str], dict] = {
    # copilot-cli §6.3 — workspace.yaml present → canonical id (§4)
    ("copilot-cli", "alpha"): {
        "id_present": True, "close": "explicit", "warning_codes": [],
    },
    ("copilot-cli", "beta"): {
        "id_present": True, "close": "inferred", "warning_codes": ["no-end-marker"],
    },
    # flat .jsonl has no workspace.yaml → hashless native id → id null +
    # unknown-workspace (§4); shutdown still closes it cleanly
    ("copilot-cli", "gamma"): {
        "id_present": False, "close": "explicit",
        "warning_codes": ["unknown-workspace"],
    },
    ("copilot-cli", "delta"): {
        "id_present": True, "close": "explicit", "warning_codes": [],
    },
    # codex-cli §6.4 — threads have no close marker at all: stale → inferred
    # close + mandatory no-end-marker (§5.3), for both has_user_event values
    ("codex-cli", "thread-a"): {
        "id_present": True, "close": "inferred", "warning_codes": ["no-end-marker"],
    },
    ("codex-cli", "thread-b"): {
        "id_present": True, "close": "inferred", "warning_codes": ["no-end-marker"],
    },
    ("codex-cli", "rollout-closed"): {
        "id_present": True, "close": "explicit", "warning_codes": [],
    },
    ("codex-cli", "rollout-open"): {
        "id_present": True, "close": "open", "warning_codes": ["session-open"],
    },
    ("codex-cli", "rollout-exec-claim"): {
        "id_present": True, "close": "explicit", "warning_codes": [],
    },
    ("codex-cli", "rollout-bare-claim"): {
        "id_present": True, "close": "explicit", "warning_codes": [],
    },
    # vscode-chat §6.5 — wsDir name is the workspace hash verbatim; completed
    # last request is a task-complete-style close (§5.1)
    ("vscode-chat", "snap-a"): {
        "id_present": True, "close": "explicit", "warning_codes": [],
    },
    ("vscode-chat", "log-b"): {
        "id_present": True, "close": "explicit", "warning_codes": ["truncated-tail"],
    },
    # global storage → workspace_hash null is a legitimate identity per spec,
    # NOT unknown-workspace — but a hashless native id still means id null (§4)
    ("vscode-chat", "global-c"): {
        "id_present": False, "close": "explicit", "warning_codes": [],
    },
}

# Source-level (not per-session) warnings: the codex rollout that duplicates a
# state-db thread id + workspace is skipped and surfaced as `duplicates` (§6.4).
_SOURCE_WARNINGS: dict[str, list[str]] = {
    "copilot-cli": [],
    "codex-cli": ["duplicates"],
    "vscode-chat": [],
}

# ---------------------------------------------------------------------------
# Evidence manifest (docs/SESSION-EVIDENCE.md §8)
#
# Closed vocabularies the evidence manifest may declare — pinned so a typo
# can't silently widen the contract, same discipline as ALLOWED_WARNING_CODES.
# ---------------------------------------------------------------------------

# Claim kinds — the qa-pack deliverable-claim vocabulary.
ALLOWED_CLAIM_KINDS = frozenset(
    {"tests", "commit", "file", "push", "http", "url"}
)
# Manifest-side verdict vocabulary: what the corpus evidence says about the
# claim. `verified` — a recorded tool call corroborates it (e.g. pytest exit
# 0); `unverified` — tool evidence exists but does not corroborate;
# `no-evidence` — the claim text exists but no tool call is recorded.
ALLOWED_CLAIM_VERDICTS = frozenset({"verified", "unverified", "no-evidence"})
# Normalized roles/kinds from SESSION-EVIDENCE §3/§4.
ALLOWED_MESSAGE_ROLES = frozenset({"user", "assistant", "tool", "system"})
ALLOWED_TOOL_CALL_KINDS = frozenset({"execute", "write", "other", "unknown"})

# Per-session evidence expectations, hand-derived like _EXPECT. Every corpus
# session gets an entry; sessions whose store carries no content layer (codex
# `threads` rows, task-marker-only rollouts) keep all-empty expectations —
# present and minimal, never omitted.
_EVIDENCE_EXPECT: dict[tuple[str, str], dict] = {
    # copilot-cli — *.message events → roles; tool.execution_* pair → one
    # execute call; alpha's pytest exit-0 corroborates its claim.
    ("copilot-cli", "alpha"): {
        "claims": [{"kind": "tests", "verdict": "verified"}],
        "tool_call_kinds": ["execute"],
        "message_roles": ["assistant", "user"],
    },
    ("copilot-cli", "beta"): {
        "claims": [], "tool_call_kinds": [],
        "message_roles": ["assistant", "user"],
    },
    # flat file: user.message only — start/shutdown drive metadata, not roles
    ("copilot-cli", "gamma"): {
        "claims": [], "tool_call_kinds": [], "message_roles": ["user"],
    },
    ("copilot-cli", "delta"): {
        "claims": [], "tool_call_kinds": [],
        "message_roles": ["assistant", "user"],
    },
    # codex-cli — threads carry metadata only; task-marker rollouts have no
    # content records; the two claim rollouts carry response_item records.
    ("codex-cli", "thread-a"): {
        "claims": [], "tool_call_kinds": [], "message_roles": [],
    },
    ("codex-cli", "thread-b"): {
        "claims": [], "tool_call_kinds": [], "message_roles": [],
    },
    ("codex-cli", "rollout-closed"): {
        "claims": [], "tool_call_kinds": [], "message_roles": [],
    },
    ("codex-cli", "rollout-open"): {
        "claims": [], "tool_call_kinds": [], "message_roles": [],
    },
    ("codex-cli", "rollout-exec-claim"): {
        "claims": [{"kind": "tests", "verdict": "verified"}],
        "tool_call_kinds": ["execute"],
        "message_roles": ["assistant", "user"],
    },
    ("codex-cli", "rollout-bare-claim"): {
        "claims": [{"kind": "tests", "verdict": "no-evidence"}],
        "tool_call_kinds": [],
        "message_roles": ["assistant", "user"],
    },
    # vscode-chat — snap-a's response parts hold the claim + a terminal
    # toolInvocation; log-b/global-c requests carry no response content.
    ("vscode-chat", "snap-a"): {
        "claims": [{"kind": "tests", "verdict": "verified"}],
        "tool_call_kinds": ["execute"],
        "message_roles": ["assistant", "user"],
    },
    ("vscode-chat", "log-b"): {
        "claims": [], "tool_call_kinds": [], "message_roles": ["user"],
    },
    ("vscode-chat", "global-c"): {
        "claims": [], "tool_call_kinds": [], "message_roles": ["user"],
    },
}

# Corpus text is LF-canonical: consumers byte-compare the vendored files on
# every platform, so the corpus carries its own .gitattributes — without it a
# core.autocrlf=true checkout would materialize CRLF.
_GITATTRIBUTES = """\
# Corpus artifacts are LF-canonical: the parity contract compares bytes
# across platforms, so checkouts must never CRLF-ify text files even when
# the runner sets core.autocrlf=true. The sqlite store is binary.
* text eol=lf
*.sqlite -text
"""


def _session_entry(surface: str, s: dict) -> dict:
    spec = _EXPECT[(surface, s["key"])]
    if spec["close"] == "explicit":
        ended_ms = s["closed_ms"]
        assert ended_ms is not None, f"{surface}/{s['key']}: no close marker written"
    elif spec["close"] == "inferred":
        assert s["closed_ms"] is None, f"{surface}/{s['key']}: unexpected close marker"
        ended_ms = s["last_activity_ms"]
    else:  # "open"
        ended_ms = None
    codes = sorted(spec["warning_codes"])
    assert set(codes) <= ALLOWED_WARNING_CODES, (
        f"{surface}/{s['key']}: warning codes outside the spec set: {codes}"
    )
    return {
        "native_id": s["native_id"],
        "workspace_seed": s["workspace_seed"],
        "expect": {
            "id_present": spec["id_present"],
            "state": "ok",
            "warning_codes": codes,
            "event_count": s["event_count"],
            "started_at": ms_to_iso(s["started_ms"]),
            "ended_at": ms_to_iso(ended_ms) if ended_ms is not None else None,
        },
    }


def _evidence_entry(surface: str, s: dict) -> dict:
    spec = _EVIDENCE_EXPECT[(surface, s["key"])]
    kinds = sorted(spec["tool_call_kinds"])
    roles = sorted(spec["message_roles"])
    claims = sorted(spec["claims"], key=lambda c: (c["kind"], c["verdict"]))
    assert set(kinds) <= ALLOWED_TOOL_CALL_KINDS, (
        f"{surface}/{s['key']}: tool-call kinds outside the spec set: {kinds}"
    )
    assert set(roles) <= ALLOWED_MESSAGE_ROLES, (
        f"{surface}/{s['key']}: message roles outside the spec set: {roles}"
    )
    for c in claims:
        assert c["kind"] in ALLOWED_CLAIM_KINDS, (
            f"{surface}/{s['key']}: claim kind outside the spec set: {c['kind']}"
        )
        assert c["verdict"] in ALLOWED_CLAIM_VERDICTS, (
            f"{surface}/{s['key']}: claim verdict outside the spec set: "
            f"{c['verdict']}"
        )
    return {
        "surface": surface,
        "native_id": s["native_id"],
        "expected_claims": claims,
        "expected_tool_call_kinds": kinds,
        "expected_message_roles": roles,
    }


def build_session_corpus(root: str | Path, *, seed: int = DEFAULT_SEED) -> Path:
    """Write the deterministic corpus under ``root`` and return the manifest path.

    ``root`` is (re)created wholesale — the directory is owned by the
    generator, mirroring how the redact corpus regenerates its single file.
    """
    root = Path(root)
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    copilot = fixtures.create_copilot_session_state(root / "copilot", seed=seed)
    codex = fixtures.create_codex_store(root / "codex", seed=seed)
    vscode = fixtures.create_vscode_chat_storage(root / "vscode-chat", seed=seed)

    manifest = {
        "version": 1,
        "fixtures": [
            {
                "surface": "copilot-cli",
                "store_path": "copilot",
                "source_warnings": _SOURCE_WARNINGS["copilot-cli"],
                "sessions": [
                    _session_entry("copilot-cli", s) for s in copilot["sessions"]
                ],
            },
            {
                "surface": "codex-cli",
                "store_path": "codex",
                "source_warnings": _SOURCE_WARNINGS["codex-cli"],
                "sessions": [_session_entry("codex-cli", s) for s in codex["sessions"]],
            },
            {
                "surface": "vscode-chat",
                "store_path": "vscode-chat",
                "source_warnings": _SOURCE_WARNINGS["vscode-chat"],
                "sessions": [
                    _session_entry("vscode-chat", s) for s in vscode["sessions"]
                ],
            },
        ],
    }
    for fixture in manifest["fixtures"]:
        fixture["sessions"].sort(key=lambda s: s["native_id"])

    # SESSION-EVIDENCE §8 — one flat entry per session (surface repeated per
    # entry), minimal all-empty expectations where the store carries no
    # content layer. Same byte-stability rule as manifest.json.
    evidence_sessions = [
        _evidence_entry(surface, s)
        for surface, built in (
            ("copilot-cli", copilot["sessions"]),
            ("codex-cli", codex["sessions"]),
            ("vscode-chat", vscode["sessions"]),
        )
        for s in built
    ]
    evidence_sessions.sort(key=lambda s: (s["surface"], s["native_id"]))
    evidence = {
        "version": 1,
        "spec": "docs/SESSION-EVIDENCE.md",
        "sessions": evidence_sessions,
    }

    (root / ".gitattributes").write_bytes(_GITATTRIBUTES.encode("utf-8"))
    path = root / "manifest.json"
    # Bytes, not write_text: keeps the manifest LF-stable on Windows so the
    # committed corpus is byte-identical across platforms.
    path.write_bytes((json.dumps(manifest, indent=2) + "\n").encode("utf-8"))
    (root / "evidence-manifest.json").write_bytes(
        (json.dumps(evidence, indent=2) + "\n").encode("utf-8")
    )
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m devin_internals.session_corpus",
        description="Regenerate the deterministic session-surface fixture corpus "
        "(docs/SESSION-SURFACES.md §7).",
    )
    parser.add_argument("outdir", type=Path, help="corpus output directory")
    args = parser.parse_args(argv)
    manifest = build_session_corpus(args.outdir)
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
