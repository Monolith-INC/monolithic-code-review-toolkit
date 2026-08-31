#!/usr/bin/env python3.12
"""File-shaped project knowledge store: retrieval, traversal, and guarded writes.

The store is a deterministic tree of Markdown units with YAML frontmatter plus TSV
record sets, written by the `discover-project-knowledge` skill. Files are the source
of truth; everything here is derived and rebuilt when the tree changes.

Deliberately dependency-free. The MCP layer in `mcrt_knowledge_mcp.py` adds the tool
surface on top, so the store itself stays testable without installing anything, and a
host with no MCP server can reach the same data with `cat` and `grep`.
"""

from __future__ import annotations

import difflib
import fcntl
import hashlib
import math
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

SCHEMA_VERSION = 1
CATALOG_NAME = "catalog.tsv"
MANIFEST_NAME = "manifest.md"
CATALOG_COLUMNS = ("id", "type", "area", "title", "path", "provenance", "updated", "read_when")

UNIT_TYPES = ("identity", "structure", "mechanics", "rules", "evolution")
PROVENANCES = ("derived", "stated", "assumed")
STATUSES = ("current", "deprecated", "superseded")

#: `if_version` value a caller passes to create a unit that does not exist yet.
NEW_VERSION = "new"

#: Frontmatter key order. Units written by this module diff cleanly against units
#: written by the skill because both use it.
FIELD_ORDER = (
    "id", "tier", "type", "area", "title", "read_when", "provenance", "sources",
    "derived_from_commit", "updated", "version", "status", "supersedes", "links",
)

LIST_FIELDS = frozenset({"sources", "supersedes", "links"})

_ID_RE = re.compile(r"^[0-9a-z][0-9a-z._/-]*$")
_HEADING_RE = re.compile(r"^(#{2,3})\s+(.*?)\s*$")
_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Roughly four characters per token. Only ever used to keep a response inside a
# budget, so an approximation that never *under*-counts badly is what matters.
_CHARS_PER_TOKEN = 4

_BM25_K1 = 1.5
_BM25_B = 0.75


class StoreError(Exception):
    """Base for every failure a caller can recover from within the same turn."""

    kind = "error"

    def payload(self) -> dict[str, Any]:
        return {"kind": self.kind, "message": str(self)}


class UnknownUnit(StoreError):
    kind = "unknown_unit"

    def __init__(self, unit_id: str, nearest: Sequence[str]) -> None:
        super().__init__(f"no unit with id {unit_id!r}")
        self.unit_id = unit_id
        self.nearest = list(nearest)

    def payload(self) -> dict[str, Any]:
        return {**super().payload(), "id": self.unit_id, "nearest": self.nearest}


class InvalidUnitId(StoreError):
    kind = "invalid_id"


class VersionConflict(StoreError):
    """The unit moved under the caller. Carries what a same-turn retry needs."""

    kind = "version_conflict"

    def __init__(self, unit_id: str, expected: str, current: str, content: str) -> None:
        super().__init__(
            f"{unit_id} is at version {current!r}, not {expected!r}; "
            f"the current content is included so you can merge and retry"
        )
        self.unit_id = unit_id
        self.expected = expected
        self.current = current
        self.content = content

    def payload(self) -> dict[str, Any]:
        return {
            **super().payload(),
            "id": self.unit_id,
            "expected_version": self.expected,
            "current_version": self.current,
            "current_content": self.content,
        }


class PatchMismatch(StoreError):
    """`old` was not found, or was found more than once. Carries the real text."""

    kind = "patch_mismatch"

    def __init__(self, unit_id: str, occurrences: int, context: str) -> None:
        if occurrences == 0:
            detail = "was not found; the closest surrounding text is included"
        else:
            detail = f"matched {occurrences} times and must match exactly once"
        super().__init__(f"the `old` text for {unit_id} {detail}")
        self.unit_id = unit_id
        self.occurrences = occurrences
        self.context = context

    def payload(self) -> dict[str, Any]:
        return {
            **super().payload(),
            "id": self.unit_id,
            "occurrences": self.occurrences,
            "context": self.context,
        }


def normalize(text: str) -> str:
    """Lowercase and strip accents so `configuração` and `configuracao` match."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def tokenize(text: str) -> list[str]:
    return [token for token in _TOKEN_RE.findall(normalize(text)) if len(token) > 1]


def _slug(heading: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", normalize(heading))).strip("-")


def version_token(raw: bytes) -> str:
    """Content-addressed concurrency token. No sidecar state to fall out of sync."""
    return hashlib.sha256(raw).hexdigest()[:12]


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / _CHARS_PER_TOKEN)


def _scalar(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a Markdown unit into its frontmatter mapping and its body.

    Not a general YAML parser. The unit schema is a flat mapping of scalars and
    string lists, so a narrow reader rejects drift a permissive one would accept.
    """
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 3)
    if end == -1:
        return {}, text

    fields: dict[str, Any] = {}
    key: str | None = None
    for line in text[4:end + 1].splitlines():
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped.startswith("- ") and key is not None:
            fields.setdefault(key, [])
            if isinstance(fields[key], list):
                fields[key].append(_scalar(stripped[2:]))
            continue
        if ":" not in line:
            continue
        raw_key, _, raw_value = line.partition(":")
        key = raw_key.strip()
        value = raw_value.strip()
        if value == "":
            fields[key] = []
        elif value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            fields[key] = [_scalar(part) for part in inner.split(",") if part.strip()]
        else:
            fields[key] = _scalar(value)
    return fields, text[end + 5:]


def dump_frontmatter(fields: dict[str, Any]) -> str:
    """Render frontmatter in the canonical key order so writes diff cleanly."""
    ordered = [key for key in FIELD_ORDER if key in fields]
    ordered += sorted(key for key in fields if key not in FIELD_ORDER)

    lines = ["---"]
    for key in ordered:
        value = fields[key]
        if isinstance(value, list):
            if not value:
                lines.append(f"{key}: []")
            else:
                lines.append(f"{key}:")
                lines.extend(f"  - {item}" for item in value)
        elif isinstance(value, str) and (":" in value or value != value.strip()):
            lines.append(f'{key}: "{value}"')
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def parse_tsv_header(text: str) -> tuple[dict[str, Any], str]:
    """TSV units carry the same fields as leading `# key: value` comment lines."""
    fields: dict[str, Any] = {}
    lines = text.splitlines(keepends=True)
    consumed = 0
    for line in lines:
        if not line.startswith("#"):
            break
        consumed += 1
        raw = line[1:].strip()
        if ":" not in raw:
            continue
        key, _, value = raw.partition(":")
        key = key.strip()
        value = value.strip()
        if key in LIST_FIELDS:
            fields[key] = [part.strip() for part in value.split(",") if part.strip()]
        else:
            fields[key] = _scalar(value)
    return fields, "".join(lines[consumed:])


def dump_tsv_header(fields: dict[str, Any]) -> str:
    ordered = [key for key in FIELD_ORDER if key in fields]
    ordered += sorted(key for key in fields if key not in FIELD_ORDER)
    lines = []
    for key in ordered:
        value = fields[key]
        rendered = ", ".join(value) if isinstance(value, list) else value
        lines.append(f"# {key}: {rendered}")
    return "\n".join(lines) + "\n" if lines else ""


@dataclass(frozen=True)
class Section:
    """One addressable slice of a unit. `find` returns these; `fetch` serves them."""

    unit_id: str
    anchor: str
    title: str
    start_line: int
    end_line: int
    text: str


@dataclass(frozen=True)
class Unit:
    id: str
    path: Path
    fmt: str
    fields: dict[str, Any]
    body: str
    raw: str
    version: str

    @property
    def type(self) -> str:
        return str(self.fields.get("type", ""))

    @property
    def area(self) -> str:
        return str(self.fields.get("area", ""))

    @property
    def title(self) -> str:
        return str(self.fields.get("title", self.id))

    @property
    def provenance(self) -> str:
        return str(self.fields.get("provenance", "assumed"))

    @property
    def status(self) -> str:
        return str(self.fields.get("status", "current"))

    @property
    def updated(self) -> str:
        return str(self.fields.get("updated", ""))

    @property
    def read_when(self) -> str:
        return str(self.fields.get("read_when", ""))

    def sections(self) -> list[Section]:
        """Split on `##`/`###` headings; anchors are heading slugs.

        Retrieval is section-grained on purpose — returning a whole unit for a hit on
        one heading is how a search tool blows a context budget.
        """
        lines = self.body.splitlines()
        marks: list[tuple[int, str]] = []
        fenced = False
        for index, line in enumerate(lines):
            if line.lstrip().startswith("```"):
                fenced = not fenced
                continue
            if fenced:
                continue
            match = _HEADING_RE.match(line)
            if match:
                marks.append((index, match.group(2)))

        if not marks:
            return [Section(self.id, "", self.title, 1, max(len(lines), 1), self.body)]

        sections: list[Section] = []
        if marks[0][0] > 0:
            preamble = "\n".join(lines[: marks[0][0]]).strip()
            if preamble:
                sections.append(Section(self.id, "", self.title, 1, marks[0][0], preamble))

        for position, (line_no, title) in enumerate(marks):
            end = marks[position + 1][0] if position + 1 < len(marks) else len(lines)
            sections.append(
                Section(
                    unit_id=self.id,
                    anchor=_slug(title),
                    title=title,
                    start_line=line_no + 1,
                    end_line=end,
                    text="\n".join(lines[line_no:end]).strip(),
                )
            )
        return sections

    def outbound_links(self) -> list[str]:
        found = list(self.fields.get("links", []) or [])
        targets = []
        for item in found:
            targets.extend(_WIKILINK_RE.findall(item) or [item])
        targets.extend(_WIKILINK_RE.findall(self.body))
        seen: dict[str, None] = {}
        for target in targets:
            seen.setdefault(target.strip(), None)
        return list(seen)


@dataclass(frozen=True)
class Hit:
    unit_id: str
    anchor: str
    title: str
    start_line: int
    end_line: int
    score: float
    matched_terms: list[str]
    snippet: str


class KnowledgeStore:
    """Read and write a knowledge store rooted at `root`.

    The index is rebuilt whenever the tree's (path, mtime, size) signature changes,
    so an external edit — the discovery skill, or a human with an editor — is picked
    up without a restart.
    """

    def __init__(self, root: Path | str, *, today: date | None = None) -> None:
        self.root = Path(root).expanduser().resolve()
        self._signature: tuple | None = None
        self._units: dict[str, Unit] = {}
        self._backlinks: dict[str, list[str]] = {}
        # The store asks "what is today?" in two places: the recency bonus when
        # ranking, and the `updated` stamp when writing. Both go through _today()
        # so a caller that needs reproducible results can pin the clock. Left
        # unset it reads the wall clock per call, so a long-lived server still
        # sees the date roll over.
        self._pinned_today = today

    def _today(self) -> date:
        return self._pinned_today or datetime.now(UTC).date()

    # ---- loading -----------------------------------------------------------

    def _files(self) -> list[Path]:
        if not self.root.is_dir():
            return []
        found = [
            path
            for path in sorted(self.root.rglob("*"))
            if path.is_file()
            and path.suffix in {".md", ".tsv"}
            and path.name not in {CATALOG_NAME, MANIFEST_NAME}
        ]
        return found

    def _current_signature(self) -> tuple:
        return tuple(
            (str(path.relative_to(self.root)), path.stat().st_mtime_ns, path.stat().st_size)
            for path in self._files()
        )

    def _ensure_loaded(self) -> None:
        signature = self._current_signature()
        if signature == self._signature:
            return
        units: dict[str, Unit] = {}
        for path in self._files():
            unit = self._read_unit(path)
            units[unit.id] = unit

        backlinks: dict[str, list[str]] = {unit_id: [] for unit_id in units}
        for unit in units.values():
            for target in unit.outbound_links():
                if target in backlinks and unit.id not in backlinks[target]:
                    backlinks[target].append(unit.id)
        for targets in backlinks.values():
            targets.sort()

        self._units = units
        self._backlinks = backlinks
        self._signature = signature

    def _read_unit(self, path: Path) -> Unit:
        raw = path.read_text(encoding="utf-8")
        if path.suffix == ".tsv":
            fields, body = parse_tsv_header(raw)
            fmt = "tsv"
        else:
            fields, body = parse_frontmatter(raw)
            fmt = "md"
        unit_id = str(fields.get("id") or path.relative_to(self.root).with_suffix("").as_posix())
        return Unit(
            id=unit_id,
            path=path,
            fmt=fmt,
            fields=fields,
            body=body,
            raw=raw,
            version=version_token(raw.encode("utf-8")),
        )

    @property
    def units(self) -> dict[str, Unit]:
        self._ensure_loaded()
        return self._units

    def unit(self, unit_id: str) -> Unit:
        units = self.units
        if unit_id not in units:
            raise UnknownUnit(unit_id, difflib.get_close_matches(unit_id, sorted(units), n=5, cutoff=0.4))
        return units[unit_id]

    # ---- read side ---------------------------------------------------------

    def catalog(
        self,
        path_prefix: str | None = None,
        type: str | None = None,
        updated_after: str | None = None,
    ) -> list[dict[str, str]]:
        """The routing table. Descriptions only — this call never returns content."""
        rows = []
        for unit in self.units.values():
            if unit.status != "current":
                continue
            if path_prefix and not unit.id.startswith(path_prefix.strip("/")):
                continue
            if type and unit.type != type:
                continue
            if updated_after and unit.updated <= updated_after:
                continue
            rows.append(
                {
                    "id": unit.id,
                    "type": unit.type,
                    "area": unit.area,
                    "title": unit.title,
                    "path": str(unit.path.relative_to(self.root)),
                    "provenance": unit.provenance,
                    "updated": unit.updated,
                    "read_when": unit.read_when,
                }
            )
        rows.sort(key=lambda row: row["id"])
        return rows

    def facets(self) -> dict[str, list[str]]:
        types, areas, statuses, provenances = set(), set(), set(), set()
        for unit in self.units.values():
            types.add(unit.type)
            areas.add(unit.area)
            statuses.add(unit.status)
            provenances.add(unit.provenance)
        return {
            "type": sorted(value for value in types if value),
            "area": sorted(value for value in areas if value),
            "status": sorted(value for value in statuses if value),
            "provenance": sorted(value for value in provenances if value),
        }

    def _candidates(
        self,
        path_prefix: str | None,
        type: str | None,
        area: str | None,
        status: str | None,
    ) -> list[Unit]:
        selected = []
        for unit in self.units.values():
            if path_prefix and not unit.id.startswith(path_prefix.strip("/")):
                continue
            if type and unit.type != type:
                continue
            if area and unit.area != area:
                continue
            if status and unit.status != status:
                continue
            selected.append(unit)
        return sorted(selected, key=lambda unit: unit.id)

    def find(
        self,
        terms: str,
        path_prefix: str | None = None,
        type: str | None = None,
        area: str | None = None,
        status: str | None = "current",
        limit: int = 8,
    ) -> tuple[list[Hit], dict[str, Any]]:
        """Locations, never documents. Returns (hits, guidance).

        `guidance` is populated only when there are no hits: facet values that do
        exist, near-miss vocabulary, and nearest unit ids. A zero-result response
        that teaches nothing costs a turn and earns nothing.
        """
        query = tokenize(terms)
        candidates = self._candidates(path_prefix, type, area, status)

        documents: list[tuple[Unit, Section, list[str]]] = []
        for unit in candidates:
            metadata = tokenize(" ".join([unit.id.replace("/", " "), unit.title, unit.area, unit.read_when]))
            for section in unit.sections():
                documents.append((unit, section, tokenize(section.text) + metadata))

        if not query or not documents:
            return [], self._guidance(query, candidates)

        lengths = [len(tokens) for _, _, tokens in documents]
        average = sum(lengths) / len(lengths) if lengths else 0.0
        frequency: dict[str, int] = {}
        for _, _, tokens in documents:
            for token in set(tokens):
                frequency[token] = frequency.get(token, 0) + 1

        total = len(documents)
        hits: list[Hit] = []
        for (unit, section, tokens), length in zip(documents, lengths):
            counts: dict[str, int] = {}
            for token in tokens:
                counts[token] = counts.get(token, 0) + 1

            score = 0.0
            matched: list[str] = []
            for term in query:
                count = counts.get(term, 0)
                if not count:
                    continue
                matched.append(term)
                idf = math.log(1 + (total - frequency[term] + 0.5) / (frequency[term] + 0.5))
                denominator = count + _BM25_K1 * (1 - _BM25_B + _BM25_B * length / (average or 1))
                score += idf * (count * (_BM25_K1 + 1)) / denominator

            if not matched:
                continue

            identifier = tokenize(unit.id.replace("/", " ") + " " + unit.title)
            score += 0.5 * sum(1 for term in query if term in identifier)
            score += _recency_bonus(unit.updated, self._today())

            hits.append(
                Hit(
                    unit_id=unit.id,
                    anchor=section.anchor,
                    title=section.title,
                    start_line=section.start_line,
                    end_line=section.end_line,
                    score=round(score, 4),
                    matched_terms=sorted(set(matched)),
                    snippet=_snippet(section.text, query),
                )
            )

        # Deterministic: score first, then path and anchor, so repeat calls are
        # reproducible and therefore cacheable.
        hits.sort(key=lambda hit: (-hit.score, hit.unit_id, hit.anchor))
        if not hits:
            return [], self._guidance(query, candidates)
        return hits[: max(1, limit)], {}

    def _guidance(self, query: Sequence[str], candidates: Sequence[Unit]) -> dict[str, Any]:
        vocabulary: set[str] = set()
        for unit in self.units.values():
            vocabulary.update(tokenize(unit.title))
            vocabulary.update(tokenize(unit.read_when))
            vocabulary.update(tokenize(unit.id.replace("/", " ")))

        near: list[str] = []
        for term in query:
            near.extend(difflib.get_close_matches(term, sorted(vocabulary), n=3, cutoff=0.7))

        return {
            "reason": "no section matched every filter and at least one term",
            "facets": self.facets(),
            "near_miss_terms": sorted(set(near) - set(query)),
            "nearest_units": [unit.id for unit in candidates[:5]],
            "unit_count": len(self.units),
            "candidates_after_filters": len(candidates),
        }

    def fetch(
        self,
        unit_id: str,
        anchor: str | None = None,
        start_line: int | None = None,
        end_line: int | None = None,
        start_column: int = 0,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """One unit, one anchor, or one line range — always with its version token."""
        unit = self.unit(unit_id)

        if anchor:
            matches = [section for section in unit.sections() if section.anchor == anchor]
            if not matches:
                available = [section.anchor for section in unit.sections() if section.anchor]
                raise StoreError(
                    f"{unit_id} has no anchor {anchor!r}; available anchors: {', '.join(available) or 'none'}"
                )
            text = matches[0].text
            body_offset = len(unit.raw.splitlines()) - len(unit.body.splitlines())
            offset = body_offset + matches[0].start_line
        elif start_line is not None:
            lines = unit.raw.splitlines()
            stop = end_line if end_line is not None else len(lines)
            selected = lines[max(start_line - 1, 0):stop]
            if selected and start_column:
                selected[0] = selected[0][start_column:]
            text = "\n".join(selected)
            offset = start_line
        else:
            text = unit.raw
            offset = 1

        truncated = False
        continuation: dict[str, Any] | None = None
        if max_tokens is not None and estimate_tokens(text) > max_tokens:
            budget = max_tokens * _CHARS_PER_TOKEN
            lines = text.splitlines()
            kept: list[str] = []
            used = 0
            for index, line in enumerate(lines):
                if used + len(line) + 1 > budget and kept:
                    break
                if used + len(line) + 1 > budget:
                    available = max(budget - used, 1)
                    kept.append(line[:available])
                    used += available
                    continuation = {
                        "id": unit_id,
                        "anchor": None,
                        "start_line": offset + index,
                        "start_column": (start_column if index == 0 else 0) + available,
                        "remaining_lines": len(lines) - index,
                    }
                    break
                kept.append(line)
                used += len(line) + 1
            text = "\n".join(kept)
            truncated = True
            if continuation is None:
                continuation = {
                    "id": unit_id,
                    "anchor": None,
                    "start_line": offset + len(kept),
                    "start_column": 0,
                    "remaining_lines": len(lines) - len(kept),
                }

        return {
            "id": unit.id,
            "version": unit.version,
            "provenance": unit.provenance,
            "status": unit.status,
            "updated": unit.updated,
            "anchor": anchor,
            "content": text,
            "truncated": truncated,
            "continuation": continuation,
        }

    def links(self, unit_id: str, direction: str = "both") -> dict[str, list[str]]:
        """Backlinks are unreachable by grep. Without this the graph is decorative."""
        if direction not in {"in", "out", "both"}:
            raise StoreError(f"direction must be 'in', 'out' or 'both', got {direction!r}")
        unit = self.unit(unit_id)
        self._ensure_loaded()
        result: dict[str, list[str]] = {}
        if direction in {"out", "both"}:
            known = self.units
            result["out"] = sorted(target for target in unit.outbound_links() if target in known)
            result["out_unresolved"] = sorted(
                target for target in unit.outbound_links() if target not in known
            )
        if direction in {"in", "both"}:
            result["in"] = list(self._backlinks.get(unit_id, []))
        return result

    # ---- write side --------------------------------------------------------

    def _resolve(self, unit_id: str, fmt: str = "md") -> Path:
        if not _ID_RE.match(unit_id) or ".." in unit_id.split("/"):
            raise InvalidUnitId(
                f"{unit_id!r} is not a valid unit id: lowercase alphanumerics, '-', '_', '.' and '/' only"
            )
        path = (self.root / f"{unit_id}.{fmt}").resolve()
        if not path.is_relative_to(self.root):
            raise InvalidUnitId(f"{unit_id!r} resolves outside the knowledge root")
        return path

    def _existing_path(self, unit_id: str) -> Path | None:
        unit = self.units.get(unit_id)
        return unit.path if unit else None

    def _check_version(self, unit_id: str, if_version: str) -> Unit | None:
        existing = self.units.get(unit_id)
        if existing is None:
            if if_version != NEW_VERSION:
                raise StoreError(
                    f"{unit_id} does not exist yet; pass if_version={NEW_VERSION!r} to create it"
                )
            return None
        if existing.version != if_version:
            raise VersionConflict(unit_id, if_version, existing.version, existing.raw)
        return existing

    def _stamp(self, text: str, fmt: str, unit_id: str, previous: Unit | None) -> str:
        """Bump `version` and `updated` on the caller's behalf.

        A revision counter a writer has to remember to increment is a revision counter
        that silently stops moving.
        """
        today = self._today().isoformat()
        if fmt == "tsv":
            fields, body = parse_tsv_header(text)
            if not fields:
                return text
            if fields.get("id") not in {None, unit_id}:
                raise StoreError(f"frontmatter id {fields['id']!r} does not match unit id {unit_id!r}")
            fields["id"] = unit_id
            fields["updated"] = today
            fields["version"] = str(_next_version(previous, fields))
            return dump_tsv_header(fields) + body

        fields, body = parse_frontmatter(text)
        if not fields:
            return text
        if fields.get("id") not in {None, unit_id}:
            raise StoreError(f"frontmatter id {fields['id']!r} does not match unit id {unit_id!r}")
        fields["id"] = unit_id
        fields["updated"] = today
        fields["version"] = _next_version(previous, fields)
        return dump_frontmatter(fields) + body

    def _write(self, unit_id: str, path: Path, text: str, if_version: str) -> dict[str, Any]:
        """Atomically replace a unit after validating its version under a file lock."""
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.root / ".locks" / (hashlib.sha256(str(path).encode()).hexdigest() + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            current = self._read_unit(path) if path.exists() else None
            if current is None:
                if if_version != NEW_VERSION:
                    raise StoreError(
                        f"{unit_id} no longer exists; pass if_version={NEW_VERSION!r} to create it"
                    )
            elif if_version == NEW_VERSION or current.version != if_version:
                raise VersionConflict(unit_id, if_version, current.version, current.raw)

            temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
            try:
                temporary.write_text(text, encoding="utf-8")
                os.replace(temporary, path)
                self._signature = None
                self.write_catalog()
            finally:
                temporary.unlink(missing_ok=True)
        self._signature = None  # force a reload on the next read
        return {
            "id": unit_id,
            "path": str(path.relative_to(self.root)),
            "version": version_token(text.encode("utf-8")),
            "bytes": len(text.encode("utf-8")),
        }

    def put(self, unit_id: str, content: str, if_version: str) -> dict[str, Any]:
        """Create or replace a unit. `if_version` is `new` for a unit that does not exist."""
        previous = self._check_version(unit_id, if_version)
        fmt = previous.fmt if previous else _infer_format(content)
        path = previous.path if previous else self._resolve(unit_id, fmt)
        return self._write(unit_id, path, self._stamp(content, fmt, unit_id, previous), if_version)

    def patch(self, unit_id: str, old: str, new: str, if_version: str) -> dict[str, Any]:
        """Replace exactly one occurrence of `old`. A miss returns the real text."""
        previous = self._check_version(unit_id, if_version)
        if previous is None:
            raise UnknownUnit(unit_id, difflib.get_close_matches(unit_id, sorted(self.units), n=5, cutoff=0.4))

        occurrences = previous.raw.count(old)
        if occurrences != 1:
            raise PatchMismatch(unit_id, occurrences, _nearest_context(previous.raw, old))

        patched = previous.raw.replace(old, new, 1)
        return self._write(unit_id, previous.path, self._stamp(patched, previous.fmt, unit_id, previous), if_version)

    def add(self, unit_id: str, content: str, if_version: str) -> dict[str, Any]:
        """Append to a unit. History is context; appending preserves it."""
        previous = self._check_version(unit_id, if_version)
        if previous is None:
            raise UnknownUnit(unit_id, difflib.get_close_matches(unit_id, sorted(self.units), n=5, cutoff=0.4))
        joined = previous.raw.rstrip("\n") + "\n\n" + content.strip("\n") + "\n"
        return self._write(unit_id, previous.path, self._stamp(joined, previous.fmt, unit_id, previous), if_version)

    # ---- maintenance -------------------------------------------------------

    def write_catalog(self) -> Path:
        """Regenerate the routing table from the units, sorted so it is byte-stable."""
        rows = self.catalog()
        lines = ["\t".join(CATALOG_COLUMNS)]
        lines.extend("\t".join(_tsv_cell(row[column]) for column in CATALOG_COLUMNS) for row in rows)
        path = self.root / CATALOG_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return path


def _infer_format(content: str) -> str:
    """A TSV unit is comment lines followed by tab-separated rows."""
    for line in content.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        return "tsv" if "\t" in line else "md"
    return "md"


def _tsv_cell(value: str) -> str:
    return str(value).replace("\t", " ").replace("\n", " ")


def _next_version(previous: Unit | None, fields: dict[str, Any]) -> int:
    """Monotonic revision counter. A new unit starts at 1; an existing one advances."""
    source = previous.fields.get("version") if previous is not None else fields.get("version")
    try:
        current = int(str(source))
    except (TypeError, ValueError):
        return 1
    if previous is not None:
        return current + 1
    # A newly created unit is revision 1 whatever the caller pasted in.
    return 1


def _recency_bonus(updated: str, today: date) -> float:
    """A small, bounded nudge toward fresher units. Never enough to outrank relevance."""
    if not updated:
        return 0.0
    try:
        age = (today - datetime.fromisoformat(updated).date()).days
    except ValueError:
        return 0.0
    return round(0.25 * math.exp(-max(age, 0) / 365), 4)


def _snippet(text: str, query: Sequence[str], width: int = 240) -> str:
    lines = text.splitlines()
    for line in lines:
        tokens = set(tokenize(line))
        if any(term in tokens for term in query):
            return line.strip()[:width]
    return " ".join(text.split())[:width]


def _nearest_context(haystack: str, needle: str, window: int = 6) -> str:
    """The surrounding text a failed patch needs to succeed on the next attempt."""
    haystack_lines = haystack.splitlines()
    needle_lines = [line for line in needle.splitlines() if line.strip()]
    if not needle_lines:
        return "\n".join(haystack_lines[:window])

    matcher = difflib.SequenceMatcher(a=needle_lines[0])
    best_index, best_ratio = 0, 0.0
    for index, line in enumerate(haystack_lines):
        matcher.set_seq2(line)
        ratio = matcher.quick_ratio()
        if ratio > best_ratio:
            best_index, best_ratio = index, ratio

    start = max(best_index - window // 2, 0)
    return "\n".join(haystack_lines[start:start + window + len(needle_lines)])


def iter_units(root: Path | str) -> Iterator[Unit]:
    yield from KnowledgeStore(root).units.values()
