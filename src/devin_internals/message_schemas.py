"""Versioned GUI/ACP message-payload schema fixtures (docs/SCHEMA.md §2).

The store-level DDL of ``User/acp-messages/<session-uuid>.db`` is small
(``meta`` + ``messages``); the opaque part is the JSON inside
``messages.payload``. This module is the executable half of that spec
section: the corpus under ``fixtures/message-schemas/`` (also packaged as
``devin_internals/corpus/message-schemas/``) records, per
(``messages.kind``, ``meta.schema_version``), the payload *shape* — field
names, JSON types, presence and closed discriminator vocabularies — never
message contents.

Each field carries a ``status``:

- ``verified`` — observed in real captured stores (aggregate shape, no
  values kept). Verified fields are *asserted* by :func:`verify_payload`:
  a store that contradicts one fails loudly.
- ``unverified`` — documented in the spec (or in a sibling fixture for
  another store version) but never confirmed in real data. Unverified
  fields are never asserted; observing one is recorded as a promotion
  candidate instead.

Field paths use dotted segments, ``[]`` for list elements and
``["literal.key"]`` for names containing dots (the ``cognition.ai/*``
meta namespace). ``presence`` is per *parent instance*: ``always`` means
every observed parent carried the field, ``sometimes`` marks it optional.

Privacy: fixtures hold shape only — field names, types, nullability and
closed vocabularies. No message text, ids, paths or row content is ever
captured.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from importlib.resources.abc import Traversable

JSON_TYPES = frozenset({"str", "int", "float", "bool", "null", "list", "dict"})
PRESENCES = frozenset({"always", "sometimes"})
STATUSES = frozenset({"verified", "unverified"})

FORMAT_VERSION = 1
CORPUS_NAME = "message-schemas"
META_KIND = "_meta"

_MISSING = object()


class FixtureError(ValueError):
    """A message-schema fixture is malformed or self-inconsistent."""


def json_type(value: Any) -> str:
    """The JSON type name used across fixtures and verification."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return type(value).__name__


# ---------------------------------------------------------------------------
# Field paths
# ---------------------------------------------------------------------------

# A segment is (name, is_list): ("content", False) → obj["content"];
# ("content", True) → each element of obj["content"].
_Segment = tuple[str, bool]


def _parse_path(path: str) -> tuple[_Segment, ...]:
    """Parse a fixture field path into ``(name, is_list)`` segments.

    Grammar: ``segment ("." segment)*`` where a segment is ``name``,
    ``name[]`` (list elements) or ``["literal"]`` / ``["literal"][]`` for
    names containing dots (e.g. ``cognition.ai/streamingMessageId``).
    """
    segments: list[_Segment] = []
    i, n = 0, len(path)
    buf: list[str] = []

    def flush() -> None:
        name = "".join(buf)
        buf.clear()
        is_list = name.endswith("[]")
        if is_list:
            name = name[:-2]
        if not name:
            raise FixtureError(f"{path!r}: empty path segment")
        segments.append((name, is_list))

    while i < n:
        c = path[i]
        if c == ".":
            flush()
            i += 1
        elif c == "[":
            if buf:
                if path[i : i + 2] == "[]":
                    buf.append("[]")
                    i += 2
                    continue
                if i + 1 < n and path[i + 1] == '"':
                    # name["literal.key"] — the name is its own segment
                    flush()
                else:
                    raise FixtureError(
                        f"{path!r}: '[' after a name must be the [] suffix or a "
                        "quoted literal segment"
                    )
            if i + 1 >= n or path[i + 1] != '"':
                raise FixtureError(f"{path!r}: '[' must be followed by a quoted name")
            end = path.find('"]', i + 2)
            if end == -1:
                raise FixtureError(f"{path!r}: unterminated literal segment")
            literal = path[i + 2 : end]
            is_list = path[end + 2 : end + 4] == "[]"
            segments.append((literal, is_list))
            i = end + (4 if is_list else 2)
            if i < n and path[i] != ".":
                raise FixtureError(f"{path!r}: expected '.' after literal segment")
        else:
            buf.append(c)
            i += 1
    if buf:
        flush()
    elif path.endswith(".") or not segments:
        raise FixtureError(f"{path!r}: empty path segment")
    return tuple(segments)


def _format_path(segments: Iterable[_Segment]) -> str:
    parts = []
    for name, is_list in segments:
        if "." in name or "]" in name:
            parts.append(f'["{name}"]')
        else:
            parts.append(name)
        if is_list:
            parts[-1] += "[]"
    return ".".join(parts)


# ---------------------------------------------------------------------------
# Fixture model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldSpec:
    """One declared field of a payload/meta shape.

    ``segments`` is the parsed field path. ``values``/``values_unverified``
    hold *discriminator vocabulary only* (``kind``, ``sessionUpdate``,
    ``status``…) — closed sets are asserted, open ones only noted.
    """

    segments: tuple[_Segment, ...]
    types: frozenset[str]
    presence: str
    status: str
    open: bool = False
    closed: bool = False
    json_text: bool = False
    values: tuple[str, ...] = ()
    values_unverified: tuple[str, ...] = ()
    note: str | None = None

    @property
    def path(self) -> str:
        return _format_path(self.segments)

    @property
    def verified(self) -> bool:
        return self.status == "verified"

    @property
    def required(self) -> bool:
        return self.presence == "always"


@dataclass(frozen=True)
class MessageSchema:
    """One versioned fixture: payload/meta shape for one
    (``kind``, ``meta_schema_version``) pair — or the store ``meta``
    table itself (``kind == "_meta"``)."""

    kind: str
    meta_schema_version: int
    status: str
    fields: tuple[FieldSpec, ...]
    table: str = "messages"
    store_checks: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    provenance: str = ""

    @property
    def verified(self) -> bool:
        return self.status == "verified"


def _load_field(path: str, raw: Any) -> FieldSpec:
    if not isinstance(raw, dict):
        raise FixtureError(f"{path!r}: field spec must be an object")
    unknown = set(raw) - {
        "types", "presence", "status", "open", "closed", "json_text",
        "values", "documented_unverified", "note",
    }
    if unknown:
        raise FixtureError(f"{path!r}: unknown spec keys {sorted(unknown)}")
    types = raw.get("types")
    if not isinstance(types, list) or not types or not set(types) <= JSON_TYPES:
        raise FixtureError(f"{path!r}: types must be a non-empty subset of {sorted(JSON_TYPES)}")
    presence = raw.get("presence")
    if presence not in PRESENCES:
        raise FixtureError(f"{path!r}: presence must be one of {sorted(PRESENCES)}")
    status = raw.get("status")
    if status not in STATUSES:
        raise FixtureError(f"{path!r}: status must be one of {sorted(STATUSES)}")
    closed = bool(raw.get("closed", False))
    if closed and status != "verified":
        raise FixtureError(
            f"{path!r}: a closed vocabulary is an assertion — unverified fields must not close it"
        )
    values = raw.get("values", [])
    values_un = raw.get("documented_unverified", [])
    for key, vocab in (("values", values), ("documented_unverified", values_un)):
        if not isinstance(vocab, list) or not all(isinstance(v, str) for v in vocab):
            raise FixtureError(f"{path!r}: {key} must be a list of strings")
    if set(values) & set(values_un):
        raise FixtureError(f"{path!r}: values and documented_unverified must be disjoint")
    note = raw.get("note")
    if status == "unverified" and not note:
        raise FixtureError(
            f"{path!r}: unverified fields must carry a note documenting the claim's source"
        )
    return FieldSpec(
        segments=_parse_path(path),
        types=frozenset(types),
        presence=presence,
        status=status,
        open=bool(raw.get("open", False)),
        closed=closed,
        json_text=bool(raw.get("json_text", False)),
        values=tuple(values),
        values_unverified=tuple(values_un),
        note=note,
    )


def load_fixture(source: str | Path | Traversable | dict) -> MessageSchema:
    """Load one ``*.schema-v*.json`` fixture file (or an already-parsed
    dict) into a validated :class:`MessageSchema`."""
    if isinstance(source, dict):
        data = source
    else:
        try:
            text = source.read_text(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, TypeError):
            text = Path(source).read_text(encoding="utf-8")  # type: ignore[arg-type]
        data = json.loads(text)
    try:
        fixture_tag = data["fixture"]
        version = data["format_version"]
        kind = data["kind"]
        meta_version = data["meta_schema_version"]
        status = data["status"]
        fields_raw = data["fields"]
    except KeyError as exc:
        raise FixtureError(f"fixture missing required key: {exc}") from exc
    if fixture_tag != "message-schema":
        raise FixtureError(f"fixture tag must be 'message-schema', got {fixture_tag!r}")
    if version != FORMAT_VERSION:
        raise FixtureError(f"unsupported fixture format_version {version!r}")
    if status not in STATUSES:
        raise FixtureError(f"fixture status must be one of {sorted(STATUSES)}")
    table = data.get("table", "messages")
    if table not in {"messages", "meta"}:
        raise FixtureError(f"table must be 'messages' or 'meta', got {table!r}")
    if not isinstance(meta_version, int) or meta_version < 1:
        raise FixtureError(f"meta_schema_version must be a positive int, got {meta_version!r}")
    if not isinstance(fields_raw, dict) or not fields_raw:
        raise FixtureError("fields must be a non-empty object mapping paths to specs")

    specs: list[FieldSpec] = []
    seen: set[tuple[_Segment, ...]] = set()
    for path, raw in fields_raw.items():
        spec = _load_field(path, raw)
        if spec.segments in seen:
            raise FixtureError(f"{path!r}: duplicate field path")
        seen.add(spec.segments)
        specs.append(spec)

    # Honest-marking invariants, checked over the whole field set. The
    # *field* ancestors of a path are its declared dict parents plus the
    # list fields behind every [] context; a verified field must never sit
    # under an unverified one (that would assert it transitively).
    by_segments = {s.segments: s for s in specs}
    for spec in specs:
        for depth in range(1, len(spec.segments)):
            prefix = spec.segments[:depth]
            name, is_list = prefix[-1]
            if is_list:
                # the field behind an `a[]` context is `a` itself
                field_segs = prefix[:-1] + ((name, False),)
                parent = by_segments.get(field_segs)
                if parent is None:
                    raise FixtureError(
                        f"{spec.path!r}: list context {_format_path(prefix)!r} "
                        "has no declared list field behind it"
                    )
                if "list" not in parent.types:
                    raise FixtureError(
                        f"{spec.path!r}: [] under non-list field {_format_path(field_segs)!r}"
                    )
            else:
                parent = by_segments.get(prefix)
                if parent is None:
                    raise FixtureError(
                        f"{spec.path!r}: ancestor {_format_path(prefix)!r} is not declared"
                    )
                if "dict" not in parent.types and not parent.json_text:
                    raise FixtureError(
                        f"{spec.path!r}: children under non-object field "
                        f"{_format_path(prefix)!r}"
                    )
            if spec.verified and not parent.verified:
                raise FixtureError(
                    f"{spec.path!r}: verified field nested under unverified "
                    f"{_format_path(prefix)!r}"
                )
        # a leaf `a.b[]` spec asserts on elements — its list field must exist
        leaf_name, leaf_is_list = spec.segments[-1]
        if leaf_is_list:
            list_field = spec.segments[:-1] + ((leaf_name, False),)
            parent = by_segments.get(list_field)
            if parent is None or "list" not in parent.types:
                raise FixtureError(
                    f"{spec.path!r}: [] leaf under undeclared/non-list field "
                    f"{_format_path(list_field)!r}"
                )

    checks = data.get("store_checks", [])
    if table != "meta" and checks:
        raise FixtureError("store_checks only exist on the 'meta' fixture")
    unknown_checks = set(checks) - set(_STORE_CHECKS)
    if unknown_checks:
        raise FixtureError(f"unknown store_checks {sorted(unknown_checks)}")

    notes = data.get("notes", [])
    if not isinstance(notes, list) or not all(isinstance(x, str) for x in notes):
        raise FixtureError("notes must be a list of strings")

    return MessageSchema(
        kind=kind,
        meta_schema_version=meta_version,
        status=status,
        fields=tuple(specs),
        table=table,
        store_checks=tuple(checks),
        notes=tuple(notes),
        provenance=data.get("provenance", ""),
    )


# ---------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MessageSchemaCorpus:
    """All fixtures for one store family, keyed for lookup."""

    manifest: dict[str, Any]
    message_fixtures: dict[tuple[str, int], MessageSchema]
    meta_fixtures: dict[int, MessageSchema]

    def fixture_for(self, kind: str, meta_schema_version: int) -> MessageSchema | None:
        return self.message_fixtures.get((kind, meta_schema_version))

    def meta_for(self, meta_schema_version: int) -> MessageSchema | None:
        return self.meta_fixtures.get(meta_schema_version)

    @property
    def known_versions(self) -> tuple[int, ...]:
        return tuple(sorted(self.meta_fixtures))


def _iter_json_children(root: Any) -> Iterator[tuple[str, Any]]:
    """Yield ``(name, json-loaded-child)`` for a Path or Traversable dir."""
    for child in sorted(root.iterdir(), key=lambda c: c.name):
        if child.name.endswith(".json") and child.is_file():
            yield child.name, json.loads(child.read_text(encoding="utf-8"))


def load_corpus(path: str | Path | Traversable | None = None) -> MessageSchemaCorpus:
    """Load every fixture in the corpus dir plus its ``manifest.json``.

    ``path=None`` resolves the packaged corpus
    (``devin_internals/corpus/message-schemas/``) — works identically from
    the repo checkout and the installed wheel.
    """
    if path is None:
        from devin_internals.corpus_access import corpus_root

        path = corpus_root(CORPUS_NAME)
    manifest: dict[str, Any] = {}
    message_fixtures: dict[tuple[str, int], MessageSchema] = {}
    meta_fixtures: dict[int, MessageSchema] = {}
    for name, data in _iter_json_children(path):
        if name == "manifest.json":
            manifest = data
            continue
        schema = load_fixture(data)
        if schema.kind == META_KIND:
            meta_fixtures[schema.meta_schema_version] = schema
        else:
            key = (schema.kind, schema.meta_schema_version)
            if key in message_fixtures:
                raise FixtureError(f"duplicate fixture for kind={key[0]} v{key[1]}")
            message_fixtures[key] = schema
    if not manifest:
        raise FixtureError("corpus is missing manifest.json")
    if not meta_fixtures:
        raise FixtureError("corpus declares no '_meta' fixture")
    # manifest ↔ file consistency
    listed = {
        (entry["kind"], entry["meta_schema_version"])
        for entry in manifest.get("fixtures", [])
        if entry.get("table", "messages") == "messages"
    }
    if listed and listed != set(message_fixtures):
        raise FixtureError(
            "manifest fixture list disagrees with files: "
            f"missing={sorted(set(message_fixtures) - listed)} "
            f"extra={sorted(listed - set(message_fixtures))}"
        )
    return MessageSchemaCorpus(
        manifest=manifest,
        message_fixtures=message_fixtures,
        meta_fixtures=meta_fixtures,
    )


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


class _Sink:
    """Collects findings; sets dedup across rows so a large store can't
    flood the report with one repeated violation."""

    def __init__(self) -> None:
        self.contradictions: set[str] = set()
        self.promotions: set[str] = set()
        self.new_vocabulary: set[str] = set()
        self.undeclared_fields: set[str] = set()


@dataclass
class _Node:
    spec: FieldSpec | None
    children: dict[str, _Node] = field(default_factory=dict)
    item: _Node | None = None  # subtree applied to each [] element


def _field_tree(schema: MessageSchema) -> _Node:
    """Index a fixture's field paths into a verify tree."""
    root = _Node(spec=None)
    for spec in schema.fields:
        node = root
        for depth, (name, is_list) in enumerate(spec.segments):
            node = node.children.setdefault(name, _Node(spec=None))
            if is_list:
                if node.item is None:
                    node.item = _Node(spec=None)
                node = node.item
        if node.spec is not None:
            raise FixtureError(f"{spec.path!r}: duplicate field path")
        node.spec = spec
    return root


def _verify_object(obj: dict, children: dict[str, _Node], path: str,
                   sink: _Sink, ctx: str, *, open_: bool) -> None:
    if not open_:
        for key in obj:
            if key not in children:
                sink.undeclared_fields.add(
                    f"{ctx}: undeclared field {path + '.' if path else ''}{key!r}"
                )
    for name, child in children.items():
        child_path = f"{path}.{name}" if path else name
        _verify_node(child, obj.get(name, _MISSING), child_path, sink, ctx)


def _verify_node(node: _Node, value: Any, path: str, sink: _Sink, ctx: str,
                 inherited_open: bool = False) -> None:
    spec = node.spec
    if value is _MISSING:
        # Children of an absent node can't be checked either — the one
        # missing-parent report is the honest signal.
        if spec is not None and spec.verified and spec.required:
            sink.contradictions.add(f"{ctx}: missing required verified field {path}")
        return
    if spec is not None:
        if not spec.verified:
            sink.promotions.add(f"{ctx}: unverified field present: {path}")
            return  # unverified fields are never asserted, and never descended
        t = json_type(value)
        if t not in spec.types:
            sink.contradictions.add(
                f"{ctx}: {path} has type {t}, expected {'|'.join(sorted(spec.types))}"
            )
            return  # mistyped node — children would be noise
        if spec.values and isinstance(value, str):
            if value in spec.values_unverified:
                sink.promotions.add(
                    f"{ctx}: {path}={value!r} — documented-but-unverified "
                    "vocabulary observed"
                )
            elif value not in spec.values:
                if spec.closed:
                    sink.contradictions.add(
                        f"{ctx}: {path}={value!r} outside declared vocabulary "
                        f"{sorted(spec.values)}"
                    )
                else:
                    sink.new_vocabulary.add(
                        f"{ctx}: {path}={value!r} not in observed vocabulary"
                    )
        effective = value
        if spec.json_text:
            try:
                effective = json.loads(value)
            except (TypeError, json.JSONDecodeError):
                sink.contradictions.add(f"{ctx}: {path} is not valid JSON (json_text)")
                return
            if not isinstance(effective, dict):
                sink.contradictions.add(
                    f"{ctx}: {path} json_text decodes to {json_type(effective)}, "
                    "expected dict"
                )
                return
    else:
        effective = value
    # Descend. Structural nodes (spec=None, created by deeper declared
    # paths) still walk their children — only presence/assertion checks
    # are spec-gated.
    node_open = spec.open if spec is not None else inherited_open
    if node.item is not None:
        if not isinstance(effective, list):
            sink.contradictions.add(
                f"{ctx}: {path}[] — expected list, got {json_type(effective)}"
            )
            return
        for element in effective:
            _verify_node(node.item, element, f"{path}[]", sink, ctx,
                         inherited_open=node_open)
    if node.children:
        if isinstance(effective, dict):
            _verify_object(
                effective, node.children, path, sink, ctx, open_=node_open,
            )
        elif node.item is not None and isinstance(effective, list):
            pass  # list children are the item node's business
        else:
            sink.contradictions.add(
                f"{ctx}: {path} — declared children but value is {json_type(effective)}"
            )


def _verify_payload(schema: MessageSchema, tree: _Node, payload: Any) -> dict[str, list[str]]:
    sink = _Sink()
    ctx = f"kind={schema.kind}"
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, json.JSONDecodeError):
            sink.contradictions.add(f"{ctx}: payload is not valid JSON")
            return _sink_out(sink)
    if not isinstance(payload, dict):
        sink.contradictions.add(
            f"{ctx}: payload root is {json_type(payload)}, expected dict"
        )
        return _sink_out(sink)
    _verify_object(payload, tree.children, "", sink, ctx, open_=False)
    return _sink_out(sink)


def verify_payload(schema: MessageSchema, payload: Any) -> dict[str, list[str]]:
    """Verify one decoded ``messages.payload`` (or raw JSON text) against
    its kind fixture. Returns the finding sets as sorted lists."""
    return _verify_payload(schema, _field_tree(schema), payload)


def _sink_out(sink: _Sink) -> dict[str, list[str]]:
    return {
        "contradictions": sorted(sink.contradictions),
        "promotions": sorted(sink.promotions),
        "new_vocabulary": sorted(sink.new_vocabulary),
        "undeclared_fields": sorted(sink.undeclared_fields),
    }


# --- meta-level (store) verification ----------------------------------------


def _check_message_count(meta: dict[str, str], con: sqlite3.Connection,
                         sink: _Sink, ctx: str) -> None:
    raw = meta.get("message_count")
    if raw is None:
        return  # the always-field check already reported it
    try:
        declared = int(raw)
    except (TypeError, ValueError):
        sink.contradictions.add(
            f"{ctx}: meta.message_count={raw!r} is not an integer string"
        )
        return
    rows = con.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    if declared != rows:
        sink.contradictions.add(
            f"{ctx}: meta.message_count={declared} != {rows} message rows"
        )


def _check_positions(meta: dict[str, str], con: sqlite3.Connection,
                     sink: _Sink, ctx: str) -> None:
    positions = [
        r[0] for r in con.execute("SELECT position FROM messages ORDER BY position")
    ]
    if positions != list(range(len(positions))):
        sink.contradictions.add(
            f"{ctx}: messages.position is not a contiguous 0-based sequence"
        )


_STORE_CHECKS = {
    "message_count_equals_row_count": _check_message_count,
    "positions_contiguous_zero_based": _check_positions,
}


@dataclass
class VerifyReport:
    """One ``acp-messages/*.db`` verified against the corpus."""

    db: str
    meta_schema_version: int | None
    rows_checked: int
    contradictions: list[str]
    unknown_kinds: list[str]
    promotions: list[str]
    new_vocabulary: list[str]
    undeclared_fields: list[str]
    extra_meta_keys: list[str]

    @property
    def ok(self) -> bool:
        return not self.contradictions

    def to_dict(self) -> dict[str, Any]:
        return {
            "db": self.db,
            "meta_schema_version": self.meta_schema_version,
            "rows_checked": self.rows_checked,
            "ok": self.ok,
            "contradictions": self.contradictions,
            "unknown_kinds": self.unknown_kinds,
            "promotions": self.promotions,
            "new_vocabulary": self.new_vocabulary,
            "undeclared_fields": self.undeclared_fields,
            "extra_meta_keys": self.extra_meta_keys,
        }


def _connect_readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def verify_db(
    db_path: str | Path,
    corpus: MessageSchemaCorpus | None = None,
    *,
    max_rows_per_kind: int | None = None,
) -> VerifyReport:
    """Verify one ``acp-messages/*.db`` against the fixture corpus.

    Verified claims only are asserted — a missing ``always`` field, a type
    change, a closed-vocabulary violation, an unknown ``kind`` or an
    unknown ``meta.schema_version`` lands in ``contradictions`` (the
    fail-loud set). Everything else is a graded note: promotions
    (unverified field/vocabulary observed), new_vocabulary (open-vocab
    drift), undeclared_fields (payload keys no fixture documents),
    extra_meta_keys (the meta key space is open per spec).
    """
    if corpus is None:
        corpus = load_corpus()
    path = Path(db_path).expanduser()
    sink = _Sink()
    extra_meta_keys: set[str] = set()
    unknown_kinds: set[str] = set()
    rows_checked = 0

    try:
        con = _connect_readonly(path)
    except sqlite3.DatabaseError as exc:
        sink.contradictions.add(f"{path.name}: unreadable store — {exc}")
        return _report(path, None, 0, sink, unknown_kinds, extra_meta_keys)
    try:
        try:
            tables = {
                r[0]
                for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        except sqlite3.DatabaseError as exc:
            sink.contradictions.add(f"{path.name}: unreadable store — {exc}")
            return _report(path, None, 0, sink, unknown_kinds, extra_meta_keys)
        if not {"meta", "messages"} <= tables:
            sink.contradictions.add(
                f"{path.name}: missing tables — not an acp-messages store "
                f"(has {sorted(tables)})"
            )
            return _report(path, None, 0, sink, unknown_kinds, extra_meta_keys)

        meta = {
            r[0]: r[1]
            for r in con.execute("SELECT key, value FROM meta")
        }
        raw_version = meta.get("schema_version")
        try:
            version: int | None = int(raw_version) if raw_version is not None else None
        except (TypeError, ValueError):
            version = None

        meta_schema = corpus.meta_for(version) if version is not None else None
        if version is None:
            sink.contradictions.add(
                f"{path.name}: meta.schema_version missing or not an integer "
                f"({raw_version!r})"
            )
        elif meta_schema is None:
            sink.contradictions.add(
                f"{path.name}: meta.schema_version={version} has no '_meta' fixture "
                f"(known: {list(corpus.known_versions)})"
            )
        else:
            _verify_object(
                meta, _field_tree(meta_schema).children, "meta",
                sink, "meta", open_=True,
            )
            extra_meta_keys.update(
                k for k in meta
                if k not in {f.segments[0][0] for f in meta_schema.fields}
            )
            ctx = "meta"
            for check_name in meta_schema.store_checks:
                _STORE_CHECKS[check_name](meta, con, sink, ctx)

        if meta_schema is not None:
            per_kind: dict[str, int] = {}
            trees: dict[tuple[str, int], _Node] = {}
            for _position, kind, payload in con.execute(
                "SELECT position, kind, payload FROM messages ORDER BY position"
            ):
                if max_rows_per_kind is not None:
                    used = per_kind.get(kind, 0)
                    if used >= max_rows_per_kind:
                        continue
                    per_kind[kind] = used + 1
                rows_checked += 1
                schema = (
                    corpus.fixture_for(kind, version)
                    if version is not None
                    else None
                )
                if schema is None:
                    unknown_kinds.add(kind)
                    continue
                key = (kind, version)  # type: ignore[arg-type]
                if key not in trees:
                    trees[key] = _field_tree(schema)
                findings = _verify_payload(schema, trees[key], payload)
                sink.contradictions.update(findings["contradictions"])
                sink.promotions.update(findings["promotions"])
                sink.new_vocabulary.update(findings["new_vocabulary"])
                sink.undeclared_fields.update(findings["undeclared_fields"])
            for kind in sorted(unknown_kinds):
                sink.contradictions.add(
                    f"{path.name}: messages.kind={kind!r} has no fixture for "
                    f"meta.schema_version={version} — undocumented kind (drift signal)"
                )
    finally:
        con.close()
    return _report(path, version, rows_checked, sink, unknown_kinds, extra_meta_keys)


def _report(path: Path, version: int | None, rows: int, sink: _Sink,
            unknown_kinds: set[str], extra_meta_keys: set[str]) -> VerifyReport:
    return VerifyReport(
        db=str(path),
        meta_schema_version=version,
        rows_checked=rows,
        contradictions=sorted(sink.contradictions),
        unknown_kinds=sorted(unknown_kinds),
        promotions=sorted(sink.promotions),
        new_vocabulary=sorted(sink.new_vocabulary),
        undeclared_fields=sorted(sink.undeclared_fields),
        extra_meta_keys=sorted(extra_meta_keys),
    )


# ---------------------------------------------------------------------------
# Shape extraction (fixture authoring — shape only, never values)
# ---------------------------------------------------------------------------


def extract_shape(payloads: Iterable[Any]) -> dict[str, dict[str, Any]]:
    """Aggregate the shape of decoded payloads.

    Returns ``{path: {"types": [...], "presence_in_parents": [hits,
    containers]}}`` — the data a fixture author turns into
    ``always``/``sometimes`` marks. For ``a[]``-level paths ``hits`` is the
    element count, so ``hits/containers`` reads as average items per
    parent (as in the extraction reports the corpus was built from).
    Values are never recorded.
    """
    hits: dict[tuple[_Segment, ...], int] = {}
    types: dict[tuple[_Segment, ...], set[str]] = {}
    containers: dict[tuple[_Segment, ...], int] = {}

    def note(segs: tuple[_Segment, ...], value: Any) -> None:
        hits[segs] = hits.get(segs, 0) + 1
        types.setdefault(segs, set()).add(json_type(value))

    def walk(value: Any, segs: tuple[_Segment, ...]) -> None:
        if isinstance(value, dict):
            containers[segs] = containers.get(segs, 0) + 1
            for key, child in value.items():
                child_segs = segs + ((key, False),)
                note(child_segs, child)
                walk(child, child_segs)
        elif isinstance(value, list):
            for element in value:
                elem_segs = segs[:-1] + ((segs[-1][0], True),)
                note(elem_segs, element)
                walk(element, elem_segs)

    for payload in payloads:
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (TypeError, json.JSONDecodeError):
                continue
        if isinstance(payload, dict):
            walk(payload, ())

    out: dict[str, dict[str, Any]] = {}
    for segs, count in hits.items():
        out[_format_path(segs)] = {
            "types": sorted(types[segs]),
            "presence_in_parents": [count, containers.get(segs[:-1], 0)],
        }
    return dict(sorted(out.items()))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_verify(args: argparse.Namespace) -> int:
    corpus = load_corpus()
    target = Path(args.path).expanduser()
    dbs = [target] if target.is_file() else sorted(target.glob("*.db"))
    if not dbs:
        print(f"{target}: no *.db stores found")
        return 2
    reports = [
        verify_db(db, corpus, max_rows_per_kind=args.max_rows_per_kind)
        for db in dbs
    ]
    out = {
        "corpus": CORPUS_NAME,
        "known_versions": list(corpus.known_versions),
        "ok": all(r.ok for r in reports),
        "reports": [r.to_dict() for r in reports],
    }
    print(json.dumps(out, indent=2))
    return 0 if out["ok"] else 1


def _cmd_extract(args: argparse.Namespace) -> int:
    con = _connect_readonly(Path(args.path).expanduser())
    try:
        kinds = (
            [args.kind]
            if args.kind
            else [r[0] for r in con.execute("SELECT DISTINCT kind FROM messages")]
        )
        for kind in kinds:
            payloads = (
                r[0]
                for r in con.execute(
                    "SELECT payload FROM messages WHERE kind = ? ORDER BY position",
                    (kind,),
                )
            )
            shape = extract_shape(payloads)
            print(f"=== {kind} ===")
            for path, spec in shape.items():
                hits, total = spec["presence_in_parents"]
                frac = hits / total if total else 0
                print(f"  {path:60s} {spec['types']!s:24s} {frac:.2f}")
    finally:
        con.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m devin_internals.message_schemas",
        description="Verify acp-messages/*.db payload shapes against the "
        "versioned fixture corpus (docs/SCHEMA.md §2, fixtures/message-schemas/).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    verify_p = sub.add_parser("verify", help="verify one store or a whole directory")
    verify_p.add_argument("path", type=Path, help="a *.db file or an acp-messages dir")
    verify_p.add_argument(
        "--max-rows-per-kind", type=int, default=None,
        help="cap payload checks per kind per store (shape checks always run)",
    )
    verify_p.set_defaults(func=_cmd_verify)

    extract_p = sub.add_parser(
        "extract", help="print the aggregated payload shape of a store (authoring aid)"
    )
    extract_p.add_argument("path", type=Path, help="a single *.db store")
    extract_p.add_argument("--kind", default=None, help="limit to one messages.kind")
    extract_p.set_defaults(func=_cmd_extract)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
