"""Optional Graphify graph hints; PRISM remains the source and budget authority.

No Graphify installation, network, graph generation, or LLM is required. A user
can point `graphify_graph` at an existing graph.json inside the repository.
Graph relationships are advisory: only locations verified against the current
PRISM index may become source blocks, never unverified semantic claims.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from prism._vendor.graphify_retrieval import pick_seeds, walk_graph
from prism.core.errors import UserError
from prism.navigator.source_index import SourceReader
from prism.navigator.store import IndexStore, SymbolRow
from prism.navigator.text import FILLER_WORDS, tokenize

MAX_GRAPH_BYTES = 16_000_000
MAX_NODES = 50_000
MAX_EDGES = 200_000
MAX_TEXT_CHARS = 1000
_LOCATION = re.compile(r"^L?(\d+)(?:\s*[-:]\s*L?(\d+))?$", re.IGNORECASE)
_RELATION_WORDS = frozenset({"call", "caller", "use", "import", "depend", "explain"})


@dataclass(frozen=True)
class GraphNode:
    id: str
    label: str
    file: str
    start: int | None
    text: str


@dataclass(frozen=True)
class GraphHint:
    file: str
    start: int
    end: int
    symbol: SymbolRow | None


class GraphifyGraph:
    """A bounded export loaded once per IndexStore and export file revision."""

    def __init__(self, nodes: dict[str, GraphNode], adjacent: dict[str, list[str]]) -> None:
        self.nodes = nodes
        self.adjacent = adjacent
        self.label_terms = {nid: frozenset(tokenize(node.label)) for nid, node in nodes.items()}
        self.postings: dict[str, set[str]] = {}
        for nid, node in nodes.items():
            for term in set(tokenize(node.text)):
                self.postings.setdefault(term, set()).add(nid)

    @classmethod
    def load(cls, path: Path, root: Path) -> GraphifyGraph:
        with path.open("rb") as stream:
            raw = stream.read(MAX_GRAPH_BYTES + 1)
        if len(raw) > MAX_GRAPH_BYTES:
            raise UserError("Graphify graph exceeds the 16 MB retrieval limit.")
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise UserError("Graphify graph is not valid JSON; regenerate the export.") from exc
        if not isinstance(data, dict):
            raise UserError("Graphify graph must be a node-link JSON object.")
        records = data.get("nodes", [])
        edges = data.get("links", data.get("edges", []))
        if not isinstance(records, list) or not isinstance(edges, list):
            raise UserError("Graphify graph must contain nodes and links/edges lists.")
        if len(records) > MAX_NODES or len(edges) > MAX_EDGES:
            raise UserError("Graphify graph exceeds the 50,000 node / 200,000 edge limit.")
        nodes: dict[str, GraphNode] = {}
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get("id"), str):
                continue
            nid = record["id"]
            label = record.get("label")
            if not isinstance(label, str) or not label.strip():
                continue
            file = _relative_file(root, record.get("source_file"))
            location = str(record.get("source_location", ""))[:64]
            match = _LOCATION.fullmatch(location.strip())
            start = int(match[1]) if match and int(match[1]) > 0 else None
            rationale = record.get("rationale", "")
            text = label + " " + (rationale if isinstance(rationale, str) else "")
            nodes[nid] = GraphNode(nid, label[:256], file, start, text[:MAX_TEXT_CHARS])
        adjacent_sets: dict[str, set[str]] = {}
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            # Graphify exports may declare directed:false, but arc order (or
            # legacy _src/_tgt metadata) still carries the true direction.
            source = edge.get("_src", edge.get("source"))
            target = edge.get("_tgt", edge.get("target"))
            confidence = str(edge.get("confidence", "")).upper()
            if confidence not in {"EXTRACTED", "INFERRED"}:
                continue
            if not isinstance(source, str) or not isinstance(target, str):
                continue
            if source not in nodes or target not in nodes or source == target:
                continue
            # Both directions are useful for candidate discovery, but these
            # hints are deliberately not exposed as verified call/impact edges.
            adjacent_sets.setdefault(source, set()).add(target)
            adjacent_sets.setdefault(target, set()).add(source)
        return cls(nodes, {node: sorted(others) for node, others in adjacent_sets.items()})

    def hints(self, store: IndexStore, reader: SourceReader, query: str) -> list[GraphHint]:
        terms = sorted(
            {
                term
                for word in re.findall(r"[A-Za-z0-9]+", query)
                if word.lower() not in FILLER_WORDS
                for term in tokenize(word)
                if term not in _RELATION_WORDS
            }
        )
        if not terms:
            return []
        scores: list[tuple[float, str]] = []
        best: dict[str, tuple[float, str]] = {}
        candidates: dict[str, set[str]] = {}
        for term in terms:
            for nid in self.postings.get(term, ()):
                candidates.setdefault(nid, set()).add(term)
        # Score candidates in one pass, using cached postings rather than
        # tokenizing every node or rescoring the whole graph per request word.
        for nid, matching in sorted(candidates.items()):
            node = self.nodes[nid]
            label_terms = self.label_terms[nid]
            if not matching:
                continue
            coverage = len(set(terms) & label_terms) / len(terms)
            score = sum(
                (4.0 if term in label_terms else 1.0)
                * (1.0 + len(self.nodes) / max(1, len(self.postings[term]))) ** 0.25
                for term in sorted(matching)
            )
            score *= 0.25 + coverage * coverage
            if query.casefold().strip() == node.label.casefold():
                score += 100.0
            scores.append((score, node.id))
            for term in sorted(matching):
                candidate = (-(4.0 if term in label_terms else 1.0) * score, node.id)
                if term not in best or candidate < best[term]:
                    best[term] = candidate
        seeds = pick_seeds(
            scores,
            {node.id: node.label for node in self.nodes.values()},
            {term: pair[1] for term, pair in best.items()},
        )
        seed_set = set(seeds)

        def neighbors(nid: str) -> list[str]:
            # Bounded deterministic discovery; prioritize nodes with current
            # indexed source over context-only nodes and avoid hub transit.
            return sorted(
                self.adjacent.get(nid, []),
                key=lambda other: (
                    self.nodes[other].file not in store.manifest.get("files", {}),
                    other not in seed_set,
                    other,
                ),
            )

        hints: list[GraphHint] = []
        seen: set[tuple[str, int]] = set()
        for nid, _, _ in walk_graph(seeds, neighbors):
            hint = _verified_hint(self.nodes[nid], store, reader)
            if hint and (hint.file, hint.start) not in seen:
                seen.add((hint.file, hint.start))
                hints.append(hint)
                if len(hints) == 6:
                    break
        return hints


def _relative_file(root: Path, value: object) -> str:
    if not isinstance(value, str) or not value or "://" in value:
        return ""
    try:
        path = (root / value.replace("\\", "/")).resolve()
        return path.relative_to(root).as_posix()
    except (OSError, ValueError):
        return ""


def _verified_hint(node: GraphNode, store: IndexStore, reader: SourceReader) -> GraphHint | None:
    if not node.file or node.file not in store.manifest.get("files", {}):
        return None
    lines = reader.lines(node.file)
    if not lines:
        return None
    label = node.label.strip().removesuffix("()")
    # Resolve by current symbols, not an old export's line numbers. Ambiguous
    # names are skipped rather than silently guessed.
    symbols = [
        sym
        for sym in store.symbols_in_file(node.file)
        if label in (sym.name, sym.id) or sym.id.endswith("." + label)
    ]
    if len(symbols) == 1:
        symbol = symbols[0]
        return GraphHint(node.file, symbol.start, symbol.end, symbol)
    if symbols or node.start is None or node.start > len(lines):
        return None
    # A language without a PRISM parser may still use Graphify's location, but
    # only if the current line actually contains the label's searchable terms.
    terms = set(tokenize(label))
    if not terms or not terms <= set(tokenize(lines[node.start - 1])):
        return None
    return GraphHint(node.file, max(1, node.start - 2), min(len(lines), node.start + 3), None)


def graphify_hints(store: IndexStore, reader: SourceReader, query: str) -> list[GraphHint]:
    """Load only an explicitly configured local export; never auto-install or generate it."""
    from prism.config import load_config

    configured = load_config(store.root).extra.get("graphify_graph")
    if configured is None:
        return []
    if not isinstance(configured, str) or not configured.strip():
        raise UserError("graphify_graph must be a non-empty repository-relative JSON path.")
    try:
        path = (store.root / configured).resolve()
    except (OSError, ValueError) as exc:
        raise UserError("graphify_graph is not a valid local path.") from exc
    if not path.is_relative_to(store.root) or Path(configured).is_absolute():
        raise UserError("graphify_graph must stay inside this repository.")
    try:
        stat = path.stat()
    except OSError as exc:
        raise UserError("Configured Graphify graph is unavailable; update graphify_graph.") from exc
    revision = (str(path), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
    if store.graphify_revision != revision:
        try:
            graph = GraphifyGraph.load(path, store.root)
        except OSError as exc:
            raise UserError("Cannot read the configured Graphify graph.") from exc
        store.graphify_graph = graph
        store.graphify_revision = revision
    cached_graph = store.graphify_graph
    return cached_graph.hints(store, reader, query) if cached_graph is not None else []
