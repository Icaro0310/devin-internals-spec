"""IS-1: shape-only audit of ``state.vscdb``.

``state.vscdb`` (the GUI's key/value store) can hold tokens or PII. This
scanner reports, for every key: the key name, the value's *shape* (decoded
type, length, whether it parses as JSON and its top-level keys) and risk
*flags* — never the value itself, never a substring of it. Output is safe
to paste into a report or CI log.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterator

from devin_internals.parsers.state_vscdb import StateVscdbStore

# key-name fragments that usually mark credential material
_SENSITIVE_KEY = re.compile(
    r"(token|secret|password|passwd|credential|apikey|api_key|auth|cookie|"
    r"session.?id|private.?key|bearer|ssh|refresh)", re.I)
# value *shapes* that usually mark credential material — matched for a
# boolean flag only; the match itself is never returned
_JWT_SHAPE = re.compile(r"^[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}$")


@dataclass
class KeyReport:
    key: str
    value_kind: str          # json-object | json-array | string | number | bool | null | bytes | empty
    value_len: int           # decoded char/byte length
    json_keys: list[str] = field(default_factory=list)  # top-level keys if JSON object
    risk_flags: list[str] = field(default_factory=list)


def _shape(value: str) -> tuple[str, list[str]]:
    if value == "":
        return "empty", []
    stripped = value.strip()
    if stripped[:1] in "{[":
        try:
            parsed = json.loads(stripped)
        except (ValueError, TypeError):
            return "string", []
        if isinstance(parsed, dict):
            return "json-object", sorted(str(k) for k in parsed)[:50]
        if isinstance(parsed, list):
            return "json-array", []
        return type(parsed).__name__, []
    if stripped in ("true", "false"):
        return "bool", []
    if stripped == "null":
        return "null", []
    try:
        float(stripped)
    except ValueError:
        return "string", []
    return "number", []


def _flags(key: str, kind: str, value: str) -> list[str]:
    flags: list[str] = []
    if _SENSITIVE_KEY.search(key):
        flags.append("sensitive-key-name")
    if kind == "string" and _JWT_SHAPE.match(value.strip()):
        flags.append("looks-like-jwt")
    if len(value) > 100_000:
        flags.append("large-blob")
    return flags


def scan_keys(store: StateVscdbStore) -> Iterator[KeyReport]:
    """Yield one shape-report per key. Values never escape this function."""
    for key in store.keys():
        raw = store.get(key)
        value = "" if raw is None else raw
        kind, json_keys = _shape(value)
        yield KeyReport(
            key=key, value_kind=kind, value_len=len(value),
            json_keys=json_keys, risk_flags=_flags(key, kind, value),
        )


def scan(store: StateVscdbStore) -> dict[str, Any]:
    """Full shape-only audit report (safe to serialize)."""
    reports = list(scan_keys(store))
    by_prefix: dict[str, int] = {}
    for r in reports:
        head = r.key.split(".", 1)[0] if "." in r.key else r.key.split("/", 1)[0]
        by_prefix[head] = by_prefix.get(head, 0) + 1
    flagged = [r for r in reports if r.risk_flags]
    return {
        "total_keys": len(reports),
        "key_prefixes": dict(sorted(by_prefix.items(), key=lambda kv: -kv[1])),
        "flagged_keys": len(flagged),
        "keys": [
            {
                "key": r.key,
                "value_kind": r.value_kind,
                "value_len": r.value_len,
                **({"json_keys": r.json_keys} if r.json_keys else {}),
                **({"risk_flags": r.risk_flags} if r.risk_flags else {}),
            }
            for r in reports
        ],
        "note": "shapes only — no values were read into this report",
    }
