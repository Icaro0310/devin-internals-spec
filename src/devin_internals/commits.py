"""Extract git commit references from ``tool_call_state`` payloads.

Devin sessions record shell/tool traffic as JSON blobs in
``tool_call_state.tool_call_json`` (the call) and
``tool_call_state.tool_call_update_json`` (streaming updates / results).
Commits a session touched — created, inspected, pushed, linked — surface
as 40-char hex SHAs or ``<host>/<owner>/<repo>/commit/<sha>`` URLs inside
those blobs.

Only full 40-hex SHAs are extracted. Short SHAs (7+) are ambiguous
(config hashes, truncated ids, random hex) and are deliberately ignored —
precision over recall, because these refs feed the knowledge graph.

Everything is pure stdlib, read-only over the parsed rows — pass in
``SessionsStore.tool_call_state(...)`` results.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 40-hex git SHA-1 (also matches SHA-256 object ids — same length, hex).
_SHA_RE = re.compile(r"\b[0-9a-f]{40}\b")

# well-known /commit/<sha> or /commits/<sha> URL fragments carry the same
# 40-hex capture the plain regex already finds, but also name the repo.
_COMMIT_URL_RE = re.compile(
    r"https?://[^\s\"'<>)]+?/commits?/([0-9a-f]{40})\b"
)


@dataclass(frozen=True)
class CommitRef:
    """One commit reference found inside a tool-call payload."""

    session_id: str
    tool_call_id: str
    field: str  # "call" | "update"
    sha: str
    repo_url: str | None = None  # e.g. "github.com/owner/repo" when a URL


def _refs_in_text(
    text: str | None, session_id: str, tool_call_id: str, field_name: str
) -> list[CommitRef]:
    if not text:
        return []
    refs: list[CommitRef] = []
    # URLs first so the SHA can carry its repo context
    url_shas: dict[str, str] = {}
    for m in _COMMIT_URL_RE.finditer(text):
        sha = m.group(1)
        repo = m.group(0).split("/commit")[0].split("://", 1)[-1]
        url_shas.setdefault(sha, repo)
        refs.append(
            CommitRef(session_id, tool_call_id, field_name, sha, repo)
        )
    for m in _SHA_RE.finditer(text):
        sha = m.group(0)
        if sha in url_shas:
            continue  # already captured with repo context
        refs.append(CommitRef(session_id, tool_call_id, field_name, sha))
    return refs


def commit_references(tool_calls) -> list[CommitRef]:
    """All commit refs in a ``ToolCallState`` iterable.

    Accepts anything with ``session_id``, ``tool_call_id``,
    ``tool_call_json`` and ``tool_call_update_json`` attributes — typically
    ``SessionsStore.tool_call_state()`` output. Results are deduplicated
    on ``(sha, tool_call_id)`` keeping the richer (URL-carrying) record.
    """
    seen: dict[tuple[str, str], CommitRef] = {}
    for tc in tool_calls:
        for ref in (
            _refs_in_text(
                tc.tool_call_json, tc.session_id, tc.tool_call_id, "call"
            )
            + _refs_in_text(
                tc.tool_call_update_json,
                tc.session_id,
                tc.tool_call_id,
                "update",
            )
        ):
            key = (ref.sha, ref.tool_call_id)
            prev = seen.get(key)
            if prev is None or (prev.repo_url is None and ref.repo_url):
                seen[key] = ref
    return sorted(seen.values(), key=lambda r: (r.session_id, r.sha))


def commits_by_session(tool_calls) -> dict[str, set[str]]:
    """Convenience rollup: ``session_id -> {sha, ...}``."""
    out: dict[str, set[str]] = {}
    for ref in commit_references(tool_calls):
        out.setdefault(ref.session_id, set()).add(ref.sha)
    return out
