"""One-call task retrieval: exact literals, verified code, callers, tests and impact.

`prism task "<request>"` should be the only retrieval call a coding task needs. It answers with
  * literals: every exact occurrence of strings, names and quantities the request mentions
    (exhaustive over the indexed source, so the agent does not have to grep for them again),
  * blocks: the code that best matches the request, as whole small symbols or windows around
    the matching lines, with line numbers an edit can anchor to,
  * links: call sites of the primary symbol (with the calling line), and the tests to run,
  * impact: how far a change to the primary symbol reaches,
and says how far to trust it (`confidence`, `sufficient`, `next`).
"""

from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from prism._vendor.graphify_retrieval import pick_seeds, walk_graph
from prism.core.errors import UserError
from prism.core.tokens import estimate_tokens
from prism.navigator import enrich
from prism.navigator.fusion import fuse_files
from prism.navigator.impact import dependents
from prism.navigator.literals import EvidenceResult, find_literals
from prism.navigator.overview import overview_items, render_overview, wants_overview
from prism.navigator.request import request_focus, request_operations
from prism.navigator.resolve import Target
from prism.navigator.source_index import SourceIndex, SourceReader
from prism.navigator.store import IndexStore, SymbolRow
from prism.navigator.support import local_support, produces_shape
from prism.navigator.synonyms import EXPANSION_WEIGHT, related_terms
from prism.navigator.text import FILLER_WORDS, tokenize

MIN_BUDGET, MAX_BUDGET = 128, 32000
WHOLE_SYMBOL_MAX = 120  # complete local units when affordable; output budget remains the hard cap
WINDOW_PAD = 2
MERGE_GAP = 5
MAX_BLOCKS = 6
MAX_PER_FILE = 2
MAX_FILE_CANDIDATES = 25
MAX_CALLERS = 6
MAX_STRUCTURAL_CALLERS = 12
MAX_TESTS = 3
MIN_TEST_NAME = 5  # shorter names (get, post, run) would match every test
NEXT_RESERVE = 150  # characters set aside for the closing `next` guidance
LITERAL_SHARE = 0.50
LITERAL_WIDTHS = (220, 150, 110, 80, 56)  # snippet widths tried, widest first
EXPLICIT_BONUS = 60.0  # a symbol or file the request names outright
MENTIONED_BONUS = 25.0  # a code-like name in the request that resolves to one or two symbols
CODE_KINDS = ("function", "method", "class")
TEST_DEMOTION = 0.5
MIGRATION_DEMOTION = 0.35
DOC_DEMOTION = 0.4
DOC_DIRS = frozenset(["docs", "doc", "documentation"])
HEADER_PENALTY = 0.35  # imports and the module docstring match words without being the answer
MEDIUM_MARGIN = 1.5
PATH_BONUS = 0.7  # share of a path word's weight given to every block in that file
NAME_BONUS = 3.0  # operation/object words in a symbol's name outrank repeated body vocabulary
NEW_NAME_WEIGHT = 0.5  # words that only occur in names the request says are new
REINFORCE = 0.25  # share of a neighbouring block's score a caller/callee block earns
MIN_RELATIVE_SCORE = 0.25  # blocks scoring below this share of the best are noise
# When exact literal evidence is complete it already answers "where"; code beside it is only
# context, so fewer and stronger blocks are shown.
TIGHT_RELATIVE_SCORE = 0.5
# Local embeddings (optional): candidates considered, the similarity below which a symbol is
# ignored, the stronger similarity needed to add a block no word matched, how many such blocks,
# their score relative to the best lexical block, and the boost when both channels agree.
SEMANTIC_CANDIDATES = 30
SEMANTIC_MIN_COSINE = 0.25
SEMANTIC_ADD_COSINE = 0.40
SEMANTIC_ADDED = 2
SEMANTIC_SHARE = 0.6
SEMANTIC_AGREEMENT = 0.5
SEMANTIC_LEAD_COSINE = 0.28  # a clear leader (SEMANTIC_LEAD x the runner-up) above this counts
SEMANTIC_LEAD = 1.4
SEMANTIC_LEADER_SHARE = 0.9
TIGHT_MAX_BLOCKS = 3
_IMPORT_LINE = re.compile(r"^\s*(?:import|from|package|using|require)|^\s*#include")

_WORDS = re.compile(r"[^\W_]+")
_STRUCTURAL = re.compile(
    r"\b(?:who|what|which)\s+(?:calls|uses|depends|imports)\b|\bcallers?\s+of\b"
    r"|\bwhere\s+(?:is|are)\b[^?]*\bused\b|\busages?\s+of\b|\bimpact\s+of\b"
    r"|\bwhat\s+(?:breaks|would\s+break|will\s+break)\b|\bblast\s+radius\b"
    r"|\btests?\s+(?:for|covering)\b",
    re.IGNORECASE,
)
_LOCATE = re.compile(r"^\s*(?:where\s+is|which\s+file|find|locate)\b", re.IGNORECASE)
_SOURCE_RANGE = re.compile(r"^(.+):(\d+)(?:-(\d+))?$")
_FLOW_REQUEST = re.compile(
    r"\b(?:explain|trace|pipeline|data\s+flow|call\s+flow)\b"
    r"|\bhow\b.*\b(?:works?|connects?|reaches?|flows?)\b",
    re.IGNORECASE,
)


@dataclass
class _Block:
    file: str
    start: int
    end: int
    symbol: SymbolRow | None
    score: float
    hits: list[int] = field(default_factory=list)
    role: str = "candidate"
    whole: bool = False


# --- rendering ----------------------------------------------------------------------


def _loc(file: str, start: int, end: int | None = None) -> str:
    return f"{file}:{start}" if end is None or end == start else f"{file}:{start}-{end}"


def render_task(pack: dict[str, Any]) -> str:
    parts = [
        f"PRISM task · {pack['intent']} · confidence {pack['confidence']} · "
        f"{pack['budget']['used_est']}/{pack['budget']['requested']} est. tokens"
    ]
    if pack["stale_sources"]:
        parts.append("Source changed or unavailable; run prism update before relying on the index.")
    if pack.get("search_limited"):
        parts.append(
            "Exact-match search reached a limit or unavailable source; do not assume repository-wide coverage."
        )
    if pack.get("overview"):
        parts.extend(render_overview(pack["overview"]))
    if pack.get("literals") and pack.get("scope") and not pack.get("search_limited"):
        code, text = pack["scope"]
        parts.append(
            f"Scope: searched {code} code + {text} text/data files (JSON, YAML, Markdown, HTML, ...); "
            "skipped: binaries, lockfiles, ignored paths. No other line in them matches."
        )
    if pack.get("patch"):
        patch = pack["patch"]
        parts.append(
            f"Patch: `{enrich.APPLY_COMMAND} {patch['path']}` changes {patch['old']} -> {patch['new']} at all "
            f"{patch['sites']} listed sites in {patch['files']} files (checked with git apply --check); "
            "it edits only those lines. Review with git diff."
        )
    for twin in pack.get("twins", []):
        where = ", ".join(
            [_loc(twin["primary"]["file"], *twin["primary"]["lines"])]
            + [_loc(c["file"], *c["lines"]) for c in twin["copies"]]
        )
        parts.append(
            f"Twins: {twin['name']} is defined in {len(twin['copies']) + 1} files (same name and "
            f"signature, bodies {round(100 * min(c['similarity'] for c in twin['copies']))}%+ alike); "
            f"a change usually belongs in all of them: {where}"
        )
    for lit in pack.get("literals", []):
        shown = len(lit["occurrences"])
        total = f"at least {lit['total']}" if lit.get("scan_limited") else str(lit["total"])
        scope = "exhaustive" if lit["complete"] else f"{shown} of {total} shown"
        parts.append(f'Literal "{lit["text"]}" ({lit["kind"]}, {lit["total"]} found, {scope}):')
        last_file = None
        for o in lit["occurrences"]:
            if o["file"] != last_file:
                last_file = o["file"]
                parts.append(f"  {last_file}")
            parts.append(f"    {o['line']}: {o['text']}")
    if pack.get("absent"):
        parts.append("Not in the source (new names): " + ", ".join(pack["absent"]))
    for block in pack["blocks"]:
        start, end = block["lines"]
        head = f"{block['role']}: {_loc(block['file'], start, end)}"
        if block["symbol"]:
            head += f" ({block['symbol']})"
        if block.get("seen"):
            parts.append(head + " [shown earlier in this session]")
            continue
        if block["truncated"]:
            head += (
                " [new excerpt; some lines shown earlier]"
                if block.get("continued")
                else " [excerpt; inspect remaining code before editing]"
            )
        parts.append(head)
        parts.append("```\n" + block["source"] + "\n```")
    links = pack.get("links", [])
    callers = [link for link in links if link["role"] == "caller"]
    last_target = None
    for link in callers:
        if link["target"] != last_target:
            last_target = link["target"]
            parts.append(f"Callers of {last_target.rsplit('.', 1)[-1]}:")
        snippet = f": {link['snippet']}" if link.get("snippet") else ""
        parts.append(f"  {link['symbol']} {_loc(link['file'], link['line'] or 0)}{snippet}")
    if callers and pack.get("callers_omitted"):
        parts.append(f"  … {pack['callers_omitted']} more (prism context <symbol>)")
    callees = [link["symbol"] for link in links if link["role"] == "callee"]
    if callees:
        parts.append("Calls: " + ", ".join(callees))
    tests = [link["file"] for link in links if link["role"] == "test"]
    if pack.get("run"):
        parts.append("Run: " + pack["run"])
    elif tests:
        parts.append("Tests: " + ", ".join(tests))
    if pack.get("test_warning"):
        parts.append("Tests: " + pack["test_warning"])
    impact = pack.get("impact")
    if impact and impact["symbols"]:
        parts.append(
            f"Impact: {impact['symbols']} dependent symbol{'s' * (impact['symbols'] != 1)}"
            + (
                f" in {impact['files']} other file{'s' * (impact['files'] != 1)}"
                if impact["files"]
                else ""
            )
            + (f" (e.g. {', '.join(impact['top'])})" if impact["top"] else "")
        )
    for line in pack.get("history", []):
        parts.append(f"Earlier work: {line}")
    if pack.get("read_next"):
        parts.append("Missing source (read only these ranges if needed):")
        parts.extend(f"  {_loc(item['file'], *item['lines'])}" for item in pack["read_next"])
    if pack.get("read_ranges"):
        parts.append(
            "Large files, read only: "
            + "; ".join(
                f"{r['file']} offset={r['offset']} limit={r['limit']} ({r['total']} lines)"
                for r in pack["read_ranges"]
            )
        )
    if pack.get("batch"):
        parts.append(
            f"Batch: the {pack['batch']} files above are independent; read them together in one "
            "turn, then edit them together in one turn."
        )
    if pack.get("done"):
        parts.append(f"Done when: {pack['done']}")
    if not pack["blocks"] and not pack.get("literals") and not pack.get("overview"):
        parts.append("No source fits or matches; refine the query or increase the budget.")
    parts.append(f"Next: {pack['next']}")
    return "\n".join(parts)


def _size(pack: dict[str, Any]) -> int:
    # Reserve digits for the final estimate itself. Includes JSON keys/escaping, source
    # line numbers, graph links and Markdown. MCP transport envelopes are host overhead.
    pack["budget"]["used_est"] = 999999
    # The JSON form is measured compact: it is only produced on request (`--json`, format=json),
    # and its indentation must not shrink what the default text form can carry.
    return max(
        estimate_tokens(json.dumps(pack, separators=(",", ":"), ensure_ascii=False)),
        estimate_tokens(render_task(pack)),
    )


# --- helpers ------------------------------------------------------------------------


def _query_terms(query: str, index: SourceIndex) -> dict[str, float]:
    """Searchable stems in the request with their IDF weight; filler words carry no signal."""
    weights: dict[str, float] = {}
    asked: set[str] = set()
    for word in _WORDS.findall(query):
        if word.lower() in FILLER_WORDS:
            continue
        for term in tokenize(word):
            asked.add(term)
            weight = index.idf(term)
            if weight > 0:
                weights[term] = weight
    # Related words, at half weight: a request's own words always outrank them. They start from
    # what was asked, not from what the index contains ("long" is in no file, yet means lifetime).
    for term in asked:
        for other in related_terms(term):
            weight = EXPANSION_WEIGHT * index.idf(other)
            if weight > weights.get(other, 0.0):
                weights[other] = weight
    focus = request_focus(query)
    if focus != query.strip():
        for word in _WORDS.findall(focus):
            if word.lower() in FILLER_WORDS:
                continue
            for term in tokenize(word):
                weights[term] = max(weights.get(term, 0.0), 3.0 * index.idf(term))
                for other in related_terms(term):
                    weights[other] = max(
                        weights.get(other, 0.0), 3.0 * EXPANSION_WEIGHT * index.idf(other)
                    )
    return weights


def _enclosing(symbols: list[SymbolRow], line: int) -> SymbolRow | None:
    best: SymbolRow | None = None
    for sym in symbols:
        if sym.start <= line <= sym.end and (
            best is None or sym.end - sym.start < best.end - best.start
        ):
            best = sym
    return best


def _intent(query: str, identifiers: list[str], exact: bool) -> str:
    if _STRUCTURAL.search(query) and (identifiers or exact):
        return "structural"
    if _LOCATE.search(query) and not _STRUCTURAL.search(query):
        return "locate"
    return "edit"


def _windows(hits: list[int], total: int) -> list[tuple[int, int]]:
    """Line ranges around `hits`, merging hits that are close together."""
    ranges: list[tuple[int, int]] = []
    for line in sorted(set(hits)):
        lo, hi = max(1, line - WINDOW_PAD), min(total, line + WINDOW_PAD)
        if ranges and lo <= ranges[-1][1] + MERGE_GAP:
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], hi))
        else:
            ranges.append((lo, hi))
    return ranges


def _group_blocks(
    file: str,
    hits: dict[int, float],
    symbols: list[SymbolRow],
    total: int,
    terms: dict[str, float],
    prior: float,
    explained: set[tuple[str, int]],
    line_terms: dict[int, set[str]],
    operations: set[str],
) -> list[_Block]:
    """Turn scored lines of one file into blocks: whole small symbols, or windows.

    Lines an exhaustive literal list already reports exactly need only a small window, not the
    whole enclosing function."""
    by_symbol: dict[str | None, list[int]] = {}
    owner: dict[str | None, SymbolRow | None] = {}
    for line in hits:
        sym = _enclosing(symbols, line)
        key = sym.id if sym else None
        by_symbol.setdefault(key, []).append(line)
        owner[key] = sym
    blocks: list[_Block] = []
    for key, lines in by_symbol.items():
        sym = owner[key]
        # Repeated body words must not beat a short helper that covers the operation.
        covered = set().union(*(line_terms[line] for line in lines))
        score = sum(terms[t] for t in covered) + max(hits[line] for line in lines) + prior
        name_score = 0.0
        if sym is not None:
            name_terms = set(tokenize(sym.name))
            name_score = NAME_BONUS * sum(terms.get(t, 0.0) for t in name_terms)
            name_score += 4.0 * sum(terms.get(t, 0.0) for t in name_terms & operations)
            score += name_score
        reported = all((file, line) in explained for line in lines)
        if sym is not None and sym.end - sym.start + 1 <= WHOLE_SYMBOL_MAX and not reported:
            blocks.append(_Block(file, sym.start, sym.end, sym, score, lines, whole=True))
            continue
        for lo, hi in _windows(lines, total):
            inside = [line for line in lines if lo <= line <= hi]
            covered = set().union(*(line_terms[line] for line in inside))
            local = sum(terms[t] for t in covered) + max(hits[line] for line in inside)
            local += prior + name_score
            blocks.append(_Block(file, lo, hi, sym, local, inside))
    return blocks


def _render_source(lines: list[str], start: int, end: int) -> str:
    return "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1))


def _snippet(line: str | None) -> str:
    text = " ".join((line or "").split())
    return text if len(text) <= 100 else text[:99] + "…"


# --- assembly -----------------------------------------------------------------------


def build_task(
    store: IndexStore,
    query: str,
    budget: int = 2000,
    seen: set[tuple[str, int, int]] | None = None,
    mode: str = "auto",
    detail: str = "full",
) -> dict[str, Any]:
    if not MIN_BUDGET <= budget <= MAX_BUDGET:
        raise UserError(
            f"task budget must be between {MIN_BUDGET} and {MAX_BUDGET} (chars/4 estimate)"
        )
    if mode not in {"auto", "overview", "code"}:
        raise UserError("task mode must be auto, overview, or code")
    query = query.strip()
    # Optional keys (literals, absent, links, callers_omitted, impact) exist only when they have
    # content. `confidence` and `next` start at their longest values so every size check made
    # while fitting the budget already includes room for the closing text.
    pack: dict[str, Any] = {
        "intent": "edit",
        "confidence": "medium",
        "sufficient": False,
        "next": "." * NEXT_RESERVE,
        "blocks": [],
        "stale_sources": 0,
        "budget": {"requested": budget, "used_est": 0, "estimator": "ceil(chars/4)"},
    }
    if not query:
        pack["confidence"] = "low"
        pack["next"] = "Give a request, a symbol name, or a file path."
        pack["budget"]["used_est"] = _size(pack)
        return pack
    staged_seen = set(seen) if seen is not None else None
    if mode == "overview" or (mode == "auto" and wants_overview(query)):
        _overview(store, query, budget, pack)
        return pack
    with SourceIndex(store) as index:
        _fill(store, index, query, budget, staged_seen, pack, brief=detail == "brief")
    if seen is not None:
        # Only the final delivered source counts. Recovery metadata may displace
        # a peripheral block that was staged while fitting the answer.
        seen.update(
            (b["file"], b["lines"][0], b["lines"][1]) for b in pack["blocks"] if b.get("source")
        )
    return pack


def _overview(store: IndexStore, query: str, budget: int, pack: dict[str, Any]) -> None:
    reader = SourceReader(store)
    candidates = overview_items(store, reader, query)
    pack["intent"] = "overview"
    pack["confidence"] = "medium"
    pack["next"] = (
        "Map only: use the shown file or symbol for code; do not read whole files just to discover structure."
    )
    view: dict[str, Any] = {
        "files_total": candidates["files_total"],
        "symbols_total": candidates["symbols_total"],
        "files": [],
        "links": [],
        "tests": [],
        "omitted": True,
    }
    pack["overview"] = view
    if _size(pack) > budget:
        del pack["overview"]
        pack["next"] = "Overview cannot fit: increase the budget."
        pack["confidence"] = "low"
        pack["budget"]["used_est"] = _size(pack)
        return
    for key in ("languages", "dependencies"):
        view[key] = candidates[key]
        if _size(pack) > budget:
            del view[key]
    selected: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for candidate in candidates["files"]:
        row = {
            **candidate,
            "symbols": [],
            "symbols_omitted": len(candidate["symbols"]) + candidate["symbols_omitted"],
        }
        view["files"].append(row)
        if _size(pack) > budget * 0.7:
            view["files"].pop()
            continue
        selected.append((candidate, row))
    # Fill signatures across files rather than spending the map on the first
    # large class. Reserve the final quarter for relationship/test evidence.
    for depth in range(6):
        for candidate, row in selected:
            if depth >= len(candidate["symbols"]):
                continue
            row["symbols"].append(candidate["symbols"][depth])
            row["symbols_omitted"] -= 1
            if _size(pack) > budget * 0.78:
                row["symbols"].pop()
                row["symbols_omitted"] += 1
    ids = {symbol["id"] for row in view["files"] for symbol in row["symbols"]}
    files = {row["file"] for row in view["files"]}
    for link in candidates["links"]:
        if link["to"] not in ids and not (link["relation"] == "imports" and link["file"] in files):
            continue
        view["links"].append(link)
        if _size(pack) > budget:
            view["links"].pop()
    for test in candidates["tests"]:
        view["tests"].append(test)
        if _size(pack) > budget:
            view["tests"].pop()
    pack["stale_sources"] = len(reader.stale)
    # Reserve staleness digits while fitting, and trim lowest-priority map rows
    # if a concurrent edit made the final status larger.
    while _size(pack) > budget and view["links"]:
        view["links"].pop()
    while _size(pack) > budget and view["tests"]:
        view["tests"].pop()
    while _size(pack) > budget and view["files"]:
        view["files"].pop()
    if not view["files"] or pack["stale_sources"]:
        pack["confidence"] = "low"
    if _size(pack) > budget:
        del pack["overview"]
    pack["budget"]["used_est"] = _size(pack)


def _fill(
    store: IndexStore,
    index: SourceIndex,
    query: str,
    budget: int,
    seen: set[tuple[str, int, int]] | None,
    pack: dict[str, Any],
    brief: bool = False,
) -> None:
    reader = SourceReader(store)
    terms = _query_terms(query, index)
    operations = request_operations(query)
    evidence = _evidence(store, index, reader, query)
    if evidence.limited:
        pack["search_limited"] = True
    if evidence.literals:
        pack["scope"] = list(evidence.scope)
    exact_symbol = store.symbol(query)
    named = store.symbols_named(query) if query.isidentifier() else []
    exact_file = query if store.file_exists(query) else None
    requested_range: tuple[str, int, int] | None = None
    location = _SOURCE_RANGE.fullmatch(query)
    if location and store.file_exists(location[1]):
        start, end = int(location[2]), int(location[3] or location[2])
        if start < 1 or end < start:
            raise UserError("source range must use positive, ascending line numbers")
        exact_file = location[1]
        if location[3]:
            requested_range = (exact_file, start, end)
        else:
            exact_symbol = store.symbol_at(exact_file, start)
            requested_range = None if exact_symbol else (exact_file, start, end)
    if "::" in query:
        path, name = query.rsplit("::", 1)
        if store.file_exists(path):
            matches = [
                s
                for s in store.symbols_in_file(path)
                if s.name == name or s.id.endswith("." + name)
            ]
            if len(matches) == 1:
                exact_file, exact_symbol = path, matches[0]
            elif len(matches) > 1:
                raise UserError("symbol is ambiguous within this file; use its qualified name")
            else:
                raise UserError("symbol was not found in the requested file")
    exact = bool(exact_symbol or len(named) == 1 or exact_file)
    pack["intent"] = _intent(query, evidence.identifiers, exact)
    if evidence.absent:
        pack["absent"] = evidence.absent[:5]
    for name in evidence.absent:
        for term in tokenize(name):
            if term in terms:
                terms[term] *= NEW_NAME_WEIGHT

    # Candidate files: body BM25, metadata search, literal hits and anything named outright.
    ranked = index.ranked(sorted(terms), MAX_FILE_CANDIDATES)
    metadata_files: list[str] = []
    for hit in store.search(query, 40):
        hit_file: str | None = None
        if hit.kind == "symbol":
            sym = store.symbol(hit.ref)
            hit_file = sym.file if sym else None
        elif hit.kind == "module":
            mod = store.module(hit.ref)
            hit_file = mod.file if mod else None
        elif hit.kind == "file":
            hit_file = hit.ref
        if hit_file:
            metadata_files.append(hit_file)
    # Optional third channel: code the request describes in other words (local embeddings).
    similar = [] if requested_range is not None else _similar(store, query)
    similar_files = [sym.file for sym, _ in similar]
    channels = [[file for file, _ in ranked], metadata_files]
    if similar_files:
        channels.append(similar_files)
    prior = dict(fuse_files(channels, MAX_FILE_CANDIDATES))
    literal_lines = evidence.hit_lines()
    for file, _ in literal_lines:
        if store.file_exists(file):  # text/data files hold literals, never code blocks
            prior.setdefault(file, 0.2)
    definitions = _definitions(store, query, evidence, exact_symbol, named, exact_file)
    if requested_range is not None:
        file, start, end = requested_range
        lines = reader.lines(file)
        if lines is not None and end > len(lines):
            raise UserError("requested source range extends beyond the indexed file")
        definitions = [
            _Block(
                file, start, end, None, EXPLICIT_BONUS, [start], role="requested range", whole=True
            )
        ]
    for block in definitions:
        prior.setdefault(block.file, 0.5)
    candidates = (
        []
        if requested_range is not None
        else sorted(prior, key=lambda f: (-prior[f], f))[: MAX_FILE_CANDIDATES + 10]
    )

    max_weight = max(terms.values(), default=0.0)
    blocks: list[_Block] = list(definitions)
    explained = {
        key for lit in evidence.literals if lit.complete and lit.kind != "identifier"
        for key in lit.lines
    }  # fmt: skip
    for file in candidates:
        lines = reader.lines(file)
        if lines is None:
            continue
        symbols = store.symbols_in_file(file)
        header_end = min((s.start for s in symbols), default=0)
        path_bonus = PATH_BONUS * sum(terms.get(t, 0.0) for t in set(tokenize(file)))
        hits: dict[int, float] = {}
        line_terms: dict[int, set[str]] = {}
        for number, text in enumerate(lines, 1):
            bonus = literal_lines.get((file, number), 0.0)
            if not bonus and (len(text) > 400 or not text.strip()):
                continue
            tokens = set(tokenize(text)) if terms else set()
            matched = [t for t in terms if t in tokens]
            score = sum(terms[t] for t in matched) + bonus
            if (number < header_end or _IMPORT_LINE.match(text)) and symbols:
                score *= HEADER_PENALTY
            enough = bonus or (
                score >= 0.8 * max_weight
                and (len(matched) >= 2 or (matched and index.df(matched[0]) <= 5))
            )
            if enough and score > 0:
                hits[number] = score
                line_terms[number] = set(matched)
        if not hits:
            continue
        # Group before capping. A large caller's eight matching lines used to
        # eliminate a short helper in the same file before it could be ranked.
        blocks.extend(
            _group_blocks(
                file,
                hits,
                symbols,
                len(lines),
                terms,
                prior[file] + path_bonus,
                explained,
                line_terms,
                operations,
            )
        )
    if similar:
        _semantic_blocks(blocks, similar, exact or any(lit.complete for lit in evidence.literals))
    pack["stale_sources"] = len(reader.stale)
    wants_tests = bool(
        re.search(
            r"\b(?:fix|change|update|add|write|repair)\b.{0,20}\btests?\b",
            request_focus(query),
            re.I,
        )
    )
    wants_migrations = any(t.startswith("migrat") for t in terms)
    wants_docs = any(t in ("doc", "docs", "document", "documentation", "readme") for t in terms)
    from prism.navigator.feedback import boosts

    edited_before = boosts(store.root)
    for block in blocks:
        if edited_before:
            block.score *= 1.0 + edited_before.get(block.file, 0.0)
        block.score *= enrich.scope_factor(query, block.file)
        # Application code is what gets changed; tests and generated migrations rank below it
        # unless the request is about them (the same rule `prism search` applies).
        if not wants_tests and store._is_test(block.file):
            block.score *= TEST_DEMOTION
        elif not wants_migrations and "/migrations/" in f"/{block.file}":
            block.score *= MIGRATION_DEMOTION
        elif not wants_docs and block.file.split("/", 1)[0] in DOC_DIRS:
            block.score *= DOC_DEMOTION
    _edit_evidence(blocks, reader, query, terms)
    producers = [b for b in blocks if b.role == "output definition"]
    if producers and not wants_tests:
        # A verified builder and its small declared contract replace broad UI
        # consumers. Call sites are still returned through the graph below.
        contracts = [b for b in blocks if b.role == "contract"]
        blocks = producers + contracts + [b for b in definitions if b not in producers + contracts]
        blocks.extend(_constructions(store, index, reader, query, blocks))
    _reinforce(store, blocks)
    tight = any(lit.complete for lit in evidence.literals)
    blocks = _select(blocks, tight=tight)
    if not wants_tests and blocks and not store._is_test(blocks[0].file):
        # Tests belong to the primary target's verified links, not broad lexical
        # candidates matching generic words such as value/previous/null.
        related = set(_related_tests(store, index, blocks[0].symbol)) if blocks[0].symbol else set()
        blocks = [b for b in blocks if not store._is_test(b.file) or b.file in related]
    if not tight and not exact and pack["intent"] == "edit":
        blocks = _coherent_classes(store, blocks, budget)
    # A literal list or exact lookup already answers where. Expansion is for
    # connected explanations and missing evidence, not a tax on every edit.
    if not tight:
        if _FLOW_REQUEST.search(query):
            blocks.extend(_flow_blocks(store, reader, blocks, terms))
        if not exact and not producers:
            blocks.extend(_graphify_blocks(store, reader, query, blocks))
        blocks = _select(blocks)
    structural = pack["intent"] == "structural"

    # Literals first (cheap, and the part an agent would otherwise grep for), then code.
    literal_budget = int(budget * LITERAL_SHARE)
    literals: list[dict[str, Any]] = []
    pack["literals"] = literals
    for ev in evidence.literals:
        if ev.kind == "identifier" and not ev.complete:
            continue  # a partial list of a common name can't be trusted and is only noise
        # Most relevant files first, so a list that has to be cut loses the least useful lines.
        ev.occurrences.sort(
            key=lambda o: (
                store._is_test(o.file)
                or o.file.split("/", 1)[0] in DOC_DIRS
                or enrich.scope_factor(query, o.file) < 1.0,
                -prior.get(o.file, 0.0),
                o.file,
                o.line,
            )
        )
        placed = False
        # A complete list is what lets an agent edit without searching, so before dropping
        # occurrences it may take a larger share of the budget than the code excerpts.
        for limit in (literal_budget, int(budget * 0.65), int(budget * 0.8)):
            for width in LITERAL_WIDTHS:  # a narrower snippet beats a missing occurrence
                literals.append(ev.to_dict(width))
                if _size(pack) <= limit:
                    placed = True
                    break
                literals.pop()
            if placed:
                break
        for count in range(len(ev.occurrences) - 1, 0, -1):
            if placed:
                break
            literals.append(ev.to_dict(LITERAL_WIDTHS[-1], limit=count))
            if _size(pack) <= literal_budget:
                placed = True
                break
            literals.pop()
    if not literals:
        del pack["literals"]
    source_budget = max(MIN_BUDGET, int(budget * 0.80)) if budget >= 256 else budget
    patch = _safely(enrich.build_patch, store, reader, query, evidence) if literals else None
    if patch is not None:
        pack["patch"] = patch
        if _size(pack) > budget:
            del pack["patch"]
            patch = None
        else:
            # The patch carries the edit; code beside it is only context, so keep that short.
            source_budget = min(source_budget, _size(pack) + max(120, int(budget * 0.22)))
    # What earlier responses delivered, fixed before this packet adds to `seen`: a block of this
    # same packet must never turn another block of it into a "shown earlier" reference.
    earlier = set(seen) if seen is not None else None
    _fit_blocks(pack, blocks, reader, source_budget, seen, structural, earlier)
    support: list[_Block] = []
    if pack["intent"] == "edit" and not brief and patch is None:
        support = _support_blocks(store, reader, pack, source_budget, seen, earlier)

    primaries = _primaries(pack, blocks)
    if primaries:
        _links(store, index, reader, pack, primaries, budget, structural)
        if brief or patch is not None:
            _drop_graph_lines(pack)
    pack["stale_sources"] = len(reader.stale)
    _confidence(pack, evidence, blocks, terms, exact, query)
    _read_next(
        pack,
        blocks[:1] + support,
        budget,
        None
        if seen is None
        else set(seen)
        - {(b["file"], b["lines"][0], b["lines"][1]) for b in pack["blocks"] if b.get("source")},
    )
    if pack["intent"] == "edit":
        _enrich(store, reader, pack, primaries, budget)
    pack["budget"]["used_est"] = _size(pack)


_EVIDENCE_MEMO: dict[tuple[str, int, str], Any] = {}
_EVIDENCE_MEMO_LIMIT = 4


def _evidence(store: IndexStore, index: SourceIndex, reader: SourceReader, query: str) -> Any:
    """`find_literals` for this request, reused when the same request is built again at another
    budget against the same index (the exact-match search does not depend on the budget)."""
    import copy

    key = (store.root.as_posix(), id(store.manifest), query)
    hit = _EVIDENCE_MEMO.get(key)
    if hit is not None:
        return copy.deepcopy(hit)
    evidence = find_literals(index, reader, query, context_fields=_output_fields(query))
    if len(_EVIDENCE_MEMO) >= _EVIDENCE_MEMO_LIMIT:
        _EVIDENCE_MEMO.clear()
    _EVIDENCE_MEMO[key] = copy.deepcopy(evidence)
    return evidence


def _output_fields(query: str) -> set[str]:
    """Existing fields in an explicitly described output being extended."""
    if not re.search(r"\b(?:include|add|return)\b", request_focus(query), re.I):
        return set()
    shapes = [part for part in re.findall(r"\(([^()]+)\)", request_focus(query)) if "/" in part]
    fields = {
        field.strip()
        for part in shapes
        for field in part.split("/")
        if re.fullmatch(r"\s*[^\W\d]\w*\s*", field)
    }
    return fields if len(fields) >= 2 else set()


def _edit_evidence(
    blocks: list[_Block], reader: SourceReader, query: str, terms: dict[str, float]
) -> None:
    """Prefer producers of a requested object shape and exact configuration edits.

    A consumer reading fields is not their definition. This local pass verifies
    source instead of asking the model to discover the distinction in another turn.
    """
    fields = _output_fields(query)
    producer = bool(fields)
    new_blocks: list[_Block] = []
    for block in blocks:
        lines = reader.lines(block.file)
        if not lines:
            continue
        text = "\n".join(lines[block.start - 1 : block.end])
        if producer and block.symbol and block.symbol.kind in {"function", "method"}:
            defined = sum(
                bool(re.search(r"['\"]" + re.escape(name) + r"['\"]\s*:", text)) for name in fields
            )
            if (
                defined >= 2
                and block.file.endswith((".py", ".pyi"))
                and produces_shape(text, fields)
            ):
                block.score *= 3.0
                block.role = "output definition"
        if (
            producer
            and block.symbol
            and block.symbol.kind == "class"
            and re.search(r"\b(?:type|interface)\s+" + re.escape(block.symbol.name) + r"\b", text)
        ):
            defined = sum(
                bool(re.search(r"\b" + re.escape(name) + r"\??\s*:", text)) for name in fields
            )
            if defined >= 2 and block.end - block.start <= 60:
                block.role = "contract"
        # A class-level scalar is an exact edit unit, not a reason to return the
        # entire enclosing class. Keep its source location without claiming the
        # rest of the class was delivered.
        if block.symbol and block.symbol.kind == "class":
            for number in block.hits:
                match = re.match(r"\s*([A-Z][A-Z_0-9]+)\s*=\s*(\d+)\s*(?:#.*)?$", lines[number - 1])
                if match and len(set(tokenize(match[1])) & terms.keys()) >= 2:
                    new_blocks.append(
                        _Block(
                            block.file,
                            number,
                            number,
                            None,
                            block.score * 2,
                            [number],
                            role="definition",
                            whole=True,
                        )
                    )
    blocks.extend(new_blocks)
    producers = [b for b in blocks if b.role == "output definition"]
    if producers:
        for block in blocks:
            if block.role == "contract":
                block.score = max(b.score for b in producers) * 0.75


def _constructions(
    store: IndexStore, index: SourceIndex, reader: SourceReader, query: str, selected: list[_Block]
) -> list[_Block]:
    """Small literal object constructors affected by an explicitly described shape.

    These are candidates, not an exhaustive typechecker. Follow the project's
    normal type checks for indirect/spread constructions static matching misses.
    """
    fields = sorted(_output_fields(query))
    if len(fields) < 2:
        return []
    terms = [term for field in fields for term in tokenize(field)]
    paths = sorted(index.files_with_all(terms))
    result: list[_Block] = []
    score = selected[0].score * 0.65
    for file in paths[:25]:
        if not file.endswith((".ts", ".tsx", ".js", ".jsx")) or store._is_test(file):
            continue
        lines = reader.lines(file)
        if not lines:
            continue
        for number, line in enumerate(lines, 1):
            if "{" not in line or not all(
                re.search(r"\b" + re.escape(field) + r"\s*:", line) for field in fields
            ):
                continue
            if any(b.file == file and b.start <= number <= b.end for b in selected):
                continue
            result.append(
                _Block(
                    file,
                    number,
                    number,
                    None,
                    score,
                    [number],
                    role="construction candidate",
                    whole=True,
                )
            )
            if len(result) == 4:
                return result
    return result


def _support_blocks(
    store: IndexStore,
    reader: SourceReader,
    pack: dict[str, Any],
    budget: int,
    seen: set[tuple[str, int, int]] | None,
    earlier: set[tuple[str, int, int]] | None = None,
) -> list[_Block]:
    ranges: dict[str, list[tuple[int, int]]] = {}
    selected_blocks = pack["blocks"][:2]
    if (
        selected_blocks
        and selected_blocks[0]["role"] == "definition"
        and selected_blocks[0]["symbol"] is None
    ):
        selected_blocks = selected_blocks[:1]  # a scalar edit needs no helper-body expansion
    for block in selected_blocks:
        if block.get("source"):
            ranges.setdefault(block["file"], []).append(tuple(block["lines"]))
    support: list[_Block] = []
    for file, selected in ranges.items():
        for item in local_support(reader, file, selected):
            symbol = store.symbol_at(file, item.start)
            support.append(
                _Block(
                    file,
                    item.start,
                    item.end,
                    symbol,
                    1.0,
                    [item.start],
                    role="definition",
                    whole=True,
                )
            )
    # Reuse exactly the same verification, session and budget fitting as code.
    _fit_blocks(pack, support, reader, budget, seen, False, earlier)
    return [b for b in support if not _bare_import(reader, b)]


def _bare_import(reader: SourceReader, block: _Block) -> bool:
    """A one-line import. Telling the agent to read it as "missing source" only costs a turn."""
    if block.start != block.end:
        return False
    lines = reader.lines(block.file)
    if not lines or not 0 < block.start <= len(lines):
        return False
    return lines[block.start - 1].lstrip().startswith(("import ", "from ", "use ", "#include"))


def _coherent_classes(store: IndexStore, blocks: list[_Block], budget: int) -> list[_Block]:
    """Two matching methods in a small class are one coherent edit unit.

    Keep exact-symbol lookups narrow. Broader requests about cooperating methods
    should not require three retrievals for an affordable 80-line service class.
    """
    if not blocks:
        return blocks
    groups: dict[str, list[_Block]] = {}
    for block in blocks[:6]:
        if block.symbol and block.symbol.parent and block.score >= blocks[0].score * 0.4:
            groups.setdefault(block.symbol.parent, []).append(block)
    for parent, members in groups.items():
        if len({b.symbol.id for b in members if b.symbol}) < 2:
            continue
        symbol = store.symbol(parent)
        if not symbol or symbol.kind != "class" or symbol.end - symbol.start + 1 > WHOLE_SYMBOL_MAX:
            continue
        if symbol.tokens_est > budget * 0.55:
            continue  # preserve complete methods instead of forcing a truncated class
        score = max(b.score for b in members)
        combined = _Block(
            symbol.file,
            symbol.start,
            symbol.end,
            symbol,
            score,
            sorted({hit for b in members for hit in b.hits}),
            whole=True,
        )
        blocks = [
            b
            for b in blocks
            if b not in members
            and not (b.file == symbol.file and symbol.start <= b.start and b.end <= symbol.end)
        ]
        blocks.append(combined)
    return sorted(blocks, key=lambda b: (-b.score, b.file, b.start))


def _read_next(
    pack: dict[str, Any],
    blocks: list[_Block],
    budget: int,
    seen: set[tuple[str, int, int]] | None,
) -> None:
    if pack.get("patch"):
        return  # the patch carries the edit; the code beside it is context, not a gap
    delivered = set(seen or ()) | {
        (b["file"], b["lines"][0], b["lines"][1]) for b in pack["blocks"]
    }
    missing: list[dict[str, Any]] = []
    for block in blocks:
        start = block.symbol.start if block.symbol else block.start
        end = block.symbol.end if block.symbol else block.end
        for lo, hi in _unseen_ranges(block.file, start, end, delivered):
            missing.append({"file": block.file, "lines": [lo, hi]})
    if not missing:
        return
    pack["sufficient"] = False
    pack["next"] = (
        "Source is partial: read the missing ranges if needed; avoid re-reading the entire file."
    )
    if pack.get("literals") and all(lit["complete"] for lit in pack["literals"]):
        listed = [lit for lit in pack["literals"] if lit["kind"] != "identifier"]
        sites = sum(len(lit["occurrences"]) for lit in listed)
        files = len({o["file"] for lit in listed for o in lit["occurrences"]})
        pack["next"] = (
            f"Edit-ready: {sites} listed sites in {files} files are exhaustive; edit them, no "
            "repo-wide search. Read missing ranges only if needed."
            if listed
            else "Partial source: read only missing ranges if needed; complete literal lists need no re-grepping."
        )
    pack["read_next"] = []
    for item in missing[:6]:
        pack["read_next"].append(item)
        # An actionable first gap takes precedence over optional impact/caller
        # context. Never silently delete every recovery range on a full packet.
        if len(pack["read_next"]) == 1:
            while _size(pack) > budget:
                if pack.get("impact"):
                    del pack["impact"]
                elif pack.get("links"):
                    pack["links"].pop()
                    if not pack["links"]:
                        del pack["links"]
                elif len(pack["blocks"]) > 1:
                    pack["blocks"].pop()
                else:
                    break
        if _size(pack) > budget:
            pack["read_next"].pop()
    if not pack["read_next"]:
        del pack["read_next"]


def _flow_blocks(
    store: IndexStore,
    reader: SourceReader,
    blocks: list[_Block],
    terms: dict[str, float],
) -> list[_Block]:
    """Include a small connected implementation for explanation/flow requests.

    Graphify's diverse seeds avoid a single lexical collision monopolizing the
    graph. Its hub guard is paired with hard node, fan-out and two-hop caps.
    Only non-low-confidence outgoing calls are traversed; graph neighbors never
    outrank the source evidence that selected the starting point.
    """
    roots: dict[str, _Block] = {}
    for block in blocks:
        if block.symbol and block.symbol.kind in CODE_KINDS and block.score > 0:
            roots.setdefault(block.symbol.id, block)
    if not roots:
        return []
    ranked = sorted(((b.score, sid) for sid, b in roots.items()), key=lambda p: (-p[0], p[1]))
    best_by_term: dict[str, str] = {}
    for _, sid in ranked:
        block = roots[sid]
        symbol = block.symbol
        if symbol is None:
            continue
        for term in set(tokenize(symbol.name + " " + symbol.doc)) & terms.keys():
            best_by_term.setdefault(term, sid)
    seeds = pick_seeds(ranked, {sid: sid for sid in roots}, best_by_term, max_k=2, max_total=3)
    symbols: dict[str, SymbolRow] = {
        sid: block.symbol for sid, block in roots.items() if block.symbol is not None
    }
    adjacent: dict[str, list[str]] = {}

    def neighbors(sid: str) -> list[str]:
        if sid not in adjacent:
            links = [
                link
                for link in store.callees(sid)
                if link.confidence in {"high", "medium"} and not store._is_test(link.symbol.file)
            ]
            links.sort(
                key=lambda link: (
                    link.confidence != "high",
                    -sum(terms.get(t, 0.0) for t in sorted(set(tokenize(link.symbol.name)))),
                    link.line or 0,
                    link.symbol.id,
                )
            )
            adjacent[sid] = list(dict.fromkeys(link.symbol.id for link in links))
            symbols.update((link.symbol.id, link.symbol) for link in links)
        return adjacent[sid]

    extra: list[_Block] = []
    weights = {sid: roots[sid].score for sid in seeds}
    for sid, distance, parent in walk_graph(seeds, neighbors, max_nodes=18, max_neighbors=6):
        if distance == 0:
            continue
        weights[sid] = weights.get(parent or "", 0.0) * 0.65
        if sid in roots:
            continue
        symbol = symbols[sid]
        lines = reader.lines(symbol.file)
        if not lines or symbol.start > len(lines):
            continue
        whole = symbol.end - symbol.start + 1 <= WHOLE_SYMBOL_MAX
        end = symbol.end if whole else min(symbol.end, symbol.start + 14)
        extra.append(
            _Block(
                symbol.file,
                symbol.start,
                end,
                symbol,
                weights[sid],
                [symbol.start],
                role="dependency",
                whole=whole,
            )
        )
    return extra


def _graphify_blocks(
    store: IndexStore, reader: SourceReader, query: str, blocks: list[_Block]
) -> list[_Block]:
    from prism.navigator.graphify import graphify_hints

    hints = graphify_hints(store, reader, query)
    existing = {block.symbol.id for block in blocks if block.symbol}
    weight = max((block.score for block in blocks), default=2.0) * 0.45
    extra: list[_Block] = []
    for hint in hints:
        if hint.symbol and hint.symbol.id in existing:
            continue
        whole = hint.end - hint.start + 1 <= WHOLE_SYMBOL_MAX
        end = hint.end if whole else min(hint.end, hint.start + 14)
        extra.append(
            _Block(
                hint.file,
                hint.start,
                end,
                hint.symbol,
                weight,
                [hint.start],
                role="graphify hint",
                whole=whole,
            )
        )
    return extra


def _definitions(
    store: IndexStore,
    query: str,
    evidence: EvidenceResult,
    exact_symbol: SymbolRow | None,
    named: list[SymbolRow],
    exact_file: str | None,
) -> list[_Block]:
    """Blocks for things the request names outright: a symbol id, an identifier, a file."""
    wanted: dict[str, tuple[SymbolRow, float]] = {}

    def want(sym: SymbolRow, bonus: float) -> None:
        if sym.id not in wanted or wanted[sym.id][1] < bonus:
            wanted[sym.id] = (sym, bonus)

    if exact_symbol:
        want(exact_symbol, EXPLICIT_BONUS)
    elif len(named) == 1:
        want(named[0], EXPLICIT_BONUS)
    for name in evidence.identifiers:
        qualified = "." in name
        matches = store.symbols_with_suffix(name) if qualified else store.symbols_named(name)
        if qualified and matches:
            for sym in matches[:2]:
                want(sym, EXPLICIT_BONUS)
        elif 0 < len(matches) <= 2:
            for sym in matches:
                want(sym, MENTIONED_BONUS / len(matches))
    blocks: list[_Block] = []
    for sym, bonus in wanted.values():
        whole = sym.end - sym.start + 1 <= WHOLE_SYMBOL_MAX
        end = sym.end if whole else min(sym.end, sym.start + 14)
        blocks.append(
            _Block(sym.file, sym.start, end, sym, bonus + sym.rank, [sym.start], whole=whole)
        )
    if exact_file and not blocks:
        symbols_in_file = [s for s in store.symbols_in_file(exact_file) if s.parent is None]
        for sym in sorted(symbols_in_file, key=lambda s: -s.rank)[:3]:
            end = min(sym.end, sym.start + 14)
            blocks.append(_Block(sym.file, sym.start, end, sym, 2.0 + sym.rank, [sym.start]))
    return blocks


def _similar(store: IndexStore, query: str) -> list[tuple[SymbolRow, float]]:
    """Symbols the local embedding model finds similar to the request (empty when disabled)."""
    try:
        from prism.navigator.semantic import ranking

        found = ranking(store, request_focus(query) or query, SEMANTIC_CANDIDATES)
    except Exception:
        return []  # an optional channel must never break retrieval
    out: list[tuple[SymbolRow, float]] = []
    for sid, cosine in found:
        sym = store.symbol(sid)
        if sym is not None and cosine >= SEMANTIC_MIN_COSINE:
            out.append((sym, cosine))
    return out


def _semantic_blocks(
    blocks: list[_Block], similar: list[tuple[SymbolRow, float]], anchored: bool
) -> None:
    """Blend embedding similarity into lexical blocks. Agreement between the two channels raises
    a block; a strongly similar symbol no word matched is added only when nothing in the request
    anchors the answer (no exact name, no complete literal list), at below the best lexical score."""
    top = similar[0][1]
    relative = {sym.id: cosine / top for sym, cosine in similar}
    for block in blocks:
        if block.symbol is not None and block.symbol.id in relative:
            block.score *= 1.0 + SEMANTIC_AGREEMENT * relative[block.symbol.id]
    if anchored:
        return
    covered = {b.symbol.id for b in blocks if b.symbol is not None}
    best = max((b.score for b in blocks), default=0.0) or 1.0
    # Cosine scales differ between models; a symbol that clearly leads the runner-up is as
    # telling as a high absolute similarity.
    runner_up = similar[1][1] if len(similar) > 1 else 0.0
    leads = top >= SEMANTIC_LEAD_COSINE and top >= SEMANTIC_LEAD * runner_up
    added = 0
    for rank, (sym, cosine) in enumerate(similar):
        if added >= SEMANTIC_ADDED or sym.id in covered or sym.kind not in CODE_KINDS:
            continue
        leader = rank == 0 and leads
        if cosine < SEMANTIC_ADD_COSINE and not leader:
            break
        whole = sym.end - sym.start + 1 <= WHOLE_SYMBOL_MAX
        end = sym.end if whole else min(sym.end, sym.start + 14)
        score = best * (SEMANTIC_LEADER_SHARE if leader else SEMANTIC_SHARE * relative[sym.id])
        blocks.append(
            _Block(sym.file, sym.start, end, sym, score, [sym.start], role="similar", whole=whole)
        )
        covered.add(sym.id)
        added += 1


def _reinforce(store: IndexStore, blocks: list[_Block]) -> None:
    """Blocks that call, or are called by, other retrieved blocks are mutually supported: code
    that the request touches tends to form a connected piece of the call graph."""
    top = sorted(blocks, key=lambda b: -b.score)[:14]
    by_symbol = {b.symbol.id: b for b in top if b.symbol is not None}
    bonus: dict[str, float] = {}
    for sym_id in by_symbol:
        neighbours = {link.symbol.id for link in store.callers(sym_id)}
        neighbours |= {link.symbol.id for link in store.callees(sym_id)}
        support = sorted(
            (by_symbol[n].score for n in neighbours if n in by_symbol and n != sym_id),
            reverse=True,
        )[:3]
        bonus[sym_id] = REINFORCE * sum(support)
    for sym_id, extra in bonus.items():
        by_symbol[sym_id].score += extra


def _select(blocks: list[_Block], tight: bool = False) -> list[_Block]:
    """Highest score first, merging overlaps, dropping noise and capping blocks per file."""
    chosen: list[_Block] = []
    per_file: dict[str, int] = {}
    best = max((b.score for b in blocks), default=0.0)
    floor = (TIGHT_RELATIVE_SCORE if tight else MIN_RELATIVE_SCORE) * best
    for block in sorted(blocks, key=lambda b: (-b.score, b.file, b.start)):
        if block.score < floor:
            continue
        clash = next(
            (
                c
                for c in chosen
                if c.file == block.file and block.start <= c.end and c.start <= block.end
            ),
            None,
        )
        if clash is not None and clash.start <= block.start and block.end <= clash.end:
            # `block` sits inside a block already chosen (e.g. a method inside the class that was
            # chosen first): keep whichever is the more specific, not their union.
            if (
                block.symbol is not None
                and clash.symbol is not None
                and block.symbol.id != clash.symbol.id
                and block.end - block.start < clash.end - clash.start
            ):
                clash.symbol, clash.start, clash.end = block.symbol, block.start, block.end
                clash.hits = block.hits
            clash.score = max(clash.score, block.score)
            continue
        if clash is not None and block.start <= clash.start and clash.end <= block.end:
            continue  # the chosen block is the specific one; the container adds nothing new
        if clash is not None:
            if block.symbol is not None and (
                clash.symbol is None
                or block.symbol.end - block.symbol.start < clash.symbol.end - clash.symbol.start
            ):
                clash.symbol = block.symbol  # label the merged range by its most specific symbol
            clash.start, clash.end = min(clash.start, block.start), max(clash.end, block.end)
            clash.hits = sorted({*clash.hits, *block.hits})
            clash.score = max(clash.score, block.score)
            clash.whole = clash.whole and block.whole
            continue
        if per_file.get(block.file, 0) >= MAX_PER_FILE:
            continue
        per_file[block.file] = per_file.get(block.file, 0) + 1
        chosen.append(block)
    chosen.sort(key=lambda b: (-b.score, b.file, b.start))
    return chosen[: TIGHT_MAX_BLOCKS if tight else MAX_BLOCKS * 2]


def _fit_blocks(
    pack: dict[str, Any],
    blocks: list[_Block],
    reader: SourceReader,
    budget: int,
    seen: set[tuple[str, int, int]] | None,
    structural: bool,
    earlier: set[tuple[str, int, int]] | None = None,
) -> None:
    placed = len(pack["blocks"])
    # Read session memory as it was before this response. Parts included earlier
    # in this same packet are tracked separately, so they never become a false
    # "shown earlier" reference while the response is still being assembled.
    previous = set(earlier if earlier is not None else (seen or ()))
    included: set[tuple[str, int, int]] = {
        (b["file"], b["lines"][0], b["lines"][1]) for b in pack["blocks"] if b.get("source")
    }
    for rank, block in enumerate(blocks):
        if placed >= MAX_BLOCKS:
            break
        lines = reader.lines(block.file)
        if not lines:
            continue
        start, end = block.start, min(block.end, len(lines))
        if structural and rank == 0:
            end = min(end, start + 24)
        sym_id = block.symbol.id if block.symbol else None
        missing = _unseen_ranges(block.file, start, end, previous)
        if not missing:
            pack["blocks"].append(
                {
                    "role": block.role,
                    "file": block.file,
                    "symbol": sym_id,
                    "lines": [start, end],
                    "truncated": _partial_block(block, start, end, previous),
                    "seen": True,
                }
            )
            if _size(pack) > budget:
                pack["blocks"].pop()
            else:
                placed += 1
            continue
        # Spend on a complete primary body before smaller peripheral snippets.
        # A 45% slice used to truncate affordable functions and force a read.
        share = int(budget * (0.82 if rank == 0 else 0.35))
        original_start, original_end = start, end
        for lo, hi in missing:
            for full_start, full_end in _unseen_ranges(block.file, lo, hi, included):
                if placed >= MAX_BLOCKS:
                    break
                start, end = full_start, full_end
                focus = next((hit for hit in block.hits if start <= hit <= end), start)
                while start <= end:
                    item: dict[str, Any] = {
                        "role": block.role,
                        "file": block.file,
                        "symbol": sym_id,
                        "lines": [start, end],
                        "truncated": _partial_block(block, start, end, previous | included),
                        "source": _render_source(lines, start, end),
                    }
                    if missing != [(original_start, original_end)]:
                        item["continued"] = True
                    before = _size(pack)
                    pack["blocks"].append(item)
                    size = _size(pack)
                    if size <= budget and size - before <= share:
                        placed += 1
                        included.add((block.file, start, end))
                        # Remember the actual delivered excerpt, never the full
                        # function that a small budget forced us to truncate.
                        if seen is not None:
                            seen.add((block.file, start, end))
                        break
                    pack["blocks"].pop()
                    if end - focus >= focus - start:
                        end -= 1
                    else:
                        start += 1


def _unseen_ranges(
    file: str, start: int, end: int, seen: set[tuple[str, int, int]]
) -> list[tuple[int, int]]:
    """Subtract earlier intervals, including partial overlaps, without per-line sets."""
    missing: list[tuple[int, int]] = []
    cursor = start
    for lo, hi in sorted((lo, hi) for path, lo, hi in seen if path == file):
        if hi < cursor:
            continue
        if lo > end:
            break
        if lo > cursor:
            missing.append((cursor, min(end, lo - 1)))
        cursor = max(cursor, hi + 1)
        if cursor > end:
            break
    if cursor <= end:
        missing.append((cursor, end))
    return missing


def _partial_block(
    block: _Block, start: int, end: int, delivered: set[tuple[str, int, int]]
) -> bool:
    """A code window is partial even if it fit the budget without further trimming."""
    if block.symbol is not None:
        return bool(
            _unseen_ranges(
                block.file,
                block.symbol.start,
                block.symbol.end,
                delivered | {(block.file, start, end)},
            )
        )
    return start != block.start or end != block.end


def _primaries(pack: dict[str, Any], blocks: list[_Block], limit: int = 2) -> list[SymbolRow]:
    """The symbols the answer is about: the first code symbols among the blocks, best first."""
    by_id = {b.symbol.id: b for b in blocks if b.symbol is not None}
    candidates = [by_id[b["symbol"]] for b in pack["blocks"] if b["symbol"] in by_id]
    out: list[SymbolRow] = []
    for block in candidates:
        sym = block.symbol
        if sym is not None and sym.kind in CODE_KINDS and all(sym.id != o.id for o in out):
            out.append(sym)
        if len(out) == limit:
            break
    if not out and candidates and candidates[0].symbol is not None:
        out.append(candidates[0].symbol)
    return out


def _related_tests(store: IndexStore, index: SourceIndex, symbol: SymbolRow) -> list[str]:
    """Tests worth running for a change to `symbol`, best evidence first.

    1. tests that call it (the call graph);
    2. tests whose source mentions its name: this finds tests that reach the code through a
       framework (a Django test client hitting the URL, a React test rendering the component);
    3. otherwise the tests of the same package that import its module, closest first.
    Listing every test that merely imports the file would be noise the agent has to read past."""
    # Walk callers breadth-first so tests exercising wrappers are ranked after
    # direct tests but before textual matches. Bound cycles and high fan-out.
    found: list[str] = []
    pending = deque([(symbol, 0)])
    seen = {symbol.id}
    while pending:
        current, distance = pending.popleft()
        tests = store.tests_for_symbol(current.id)
        if store._is_test(current.file):
            tests = [current.file, *tests]
        for path in tests:
            if path not in found:
                found.append(path)
        if len(found) >= MAX_TESTS:
            return found[:MAX_TESTS]
        if distance < 3:
            for link in store.callers(current.id):
                if link.confidence == "low" or link.symbol.id in seen or len(seen) >= 64:
                    continue
                seen.add(link.symbol.id)
                pending.append((link.symbol, distance + 1))
    name_tokens = tokenize(symbol.name)
    if len(symbol.name) >= MIN_TEST_NAME and name_tokens:
        mentions = [f for f in index.files_with_all(name_tokens) if store._is_test(f)]
        found.extend(
            f
            for f in sorted(mentions, key=lambda f: (_common_prefix(f, symbol.file) * -1, f))
            if f not in found
        )
    if len(found) < MAX_TESTS:
        imported = sorted(
            store.tests_for_file(symbol.file),
            key=lambda f: (_common_prefix(f, symbol.file) * -1, f),
        )
        found.extend(f for f in imported[:2] if f not in found)
    if not found:
        found = _nearest_tests(store, symbol)
    return found[:MAX_TESTS]


def _nearest_tests(store: IndexStore, symbol: SymbolRow) -> list[str]:
    """Tests that merely sit next to the code (same folder, or named after the file).

    Used only when nothing links to the symbol: a nearby test file beats an empty answer,
    which would leave the agent to search for tests (or run none)."""
    stem = symbol.file.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower().removeprefix("_")
    scored: list[tuple[int, int, str]] = []
    for path in store.test_files():
        shared = _common_prefix(path, symbol.file)
        named = 1 if stem and stem in path.rsplit("/", 1)[-1].lower() else 0
        scored.append((-named, -shared, path))
    return [path for _, _, path in sorted(scored)[:2]]


def _common_prefix(a: str, b: str) -> int:
    """How many leading path segments two files share (a test next to its code scores highest)."""
    n = 0
    for left, right in zip(a.split("/")[:-1], b.split("/")[:-1], strict=False):
        if left != right:
            break
        n += 1
    return n


def _links(
    store: IndexStore,
    index: SourceIndex,
    reader: SourceReader,
    pack: dict[str, Any],
    primaries: list[SymbolRow],
    budget: int,
    structural: bool,
) -> None:
    first = primaries[0]
    links: list[dict[str, Any]] = []
    pack["links"] = links

    def add(item: dict[str, Any]) -> bool:
        links.append(item)
        if _size(pack) > budget:
            links.pop()
            return False
        return True

    omitted = 0
    caller_sets = {primary.id: store.callers(primary.id) for primary in primaries}
    active_primaries = sum(bool(callers) for callers in caller_sets.values())
    for number, primary in enumerate(primaries):
        limit = MAX_STRUCTURAL_CALLERS if structural else MAX_CALLERS
        if active_primaries > 1:
            limit = max(3, limit // 2)
        callers = caller_sets[primary.id]
        shown = 0
        for link in callers[:limit]:
            src = reader.lines(link.symbol.file)
            text = src[link.line - 1] if src and link.line and 0 < link.line <= len(src) else None
            item = {
                "role": "caller",
                "target": primary.id,
                "symbol": link.symbol.id,
                "file": link.symbol.file,
                "line": link.line,
                "confidence": link.confidence,
                "snippet": _snippet(text),
            }
            if not add(item):
                break
            shown += 1
        omitted += len(callers) - shown
        if number == 0:
            for link in store.callees(primary.id)[:3]:
                add({"role": "callee", "symbol": link.symbol.id, "file": link.symbol.file})
    test_paths = []
    selected_tests = list(
        dict.fromkeys(
            path for primary in primaries for path in _related_tests(store, index, primary)
        )
    )[:MAX_TESTS]
    for path in selected_tests:
        if add({"role": "test", "file": path}):
            test_paths.append(path)
    if test_paths:
        from prism.navigator.test_command import run_command

        command = run_command(store.root, test_paths)
        if command:
            pack["run"] = command
            if _size(pack) > budget:
                del pack["run"]
    elif not selected_tests:
        pack["test_warning"] = "No indexed tests found; add or identify a test before finishing."
        if _size(pack) > budget:
            del pack["test_warning"]
    if not links:
        del pack["links"]
    if omitted:
        pack["callers_omitted"] = omitted
        if _size(pack) > budget:
            del pack["callers_omitted"]
    deps = dependents(store, Target("symbol", first.file, symbol=first), depth=2)
    if deps["symbols"]:
        files = sorted(deps["files"], key=lambda f: (deps["files"][f], f))
        pack["impact"] = {"symbols": len(deps["symbols"]), "files": len(files), "top": files[:3]}
        if _size(pack) > budget:
            del pack["impact"]


def _margin(blocks: list[_Block]) -> float:
    """How far the best block stands above the next, which is what makes a lead trustworthy."""
    scores = sorted((b.score for b in blocks), reverse=True)
    if len(scores) < 2:
        return 0.0 if not scores else float("inf") if scores[0] > 0 else 0.0
    return scores[0] / scores[1] if scores[1] > 0 else float("inf")


def _named_by_request(blocks: list[_Block], terms: dict[str, float]) -> bool:
    """Is the best block's symbol named in the request (all words of a multi-word name)?"""
    if not blocks or blocks[0].symbol is None:
        return False
    parts = {t for t in tokenize(blocks[0].symbol.name) if "_" not in t}
    return len(parts) >= 2 and all(p in terms for p in parts)


def _confidence(
    pack: dict[str, Any],
    evidence: EvidenceResult,
    blocks: list[_Block],
    terms: dict[str, float],
    exact: bool,
    query: str,
) -> None:
    shown = list(pack["blocks"])
    total = sum(terms.values())
    coverage = 0.0
    for b in shown[:2]:
        # Other matching functions in this file cannot establish that this
        # particular returned block answers the request.
        got = set(tokenize(b.get("source", ""))) | set(tokenize(b["symbol"] or ""))
        if total:
            coverage = max(coverage, sum(terms[t] for t in got if t in terms) / total)
    literals = pack.get("literals", [])
    exhaustive = any(lit["complete"] and lit["kind"] != "identifier" for lit in literals)
    expected_literals = [
        lit for lit in evidence.literals if lit.kind != "identifier" or lit.complete
    ]
    incomplete_literals = any(not lit["complete"] for lit in literals) or len(literals) < len(
        expected_literals
    )
    margin = _margin(blocks)
    named = _named_by_request(blocks, terms)
    if (
        exact
        or exhaustive
        or coverage >= 0.55
        or named
        or (shown and shown[0]["role"] == "output definition")
    ):
        level = "high"
    elif coverage >= 0.3 or literals or margin >= MEDIUM_MARGIN:
        level = "medium"
    else:
        level = "low"
    focus = request_focus(query)
    if not exact and focus != query.strip():
        # Error requirements can match many unrelated helpers. They cannot
        # compensate for an entirely missing leading edit topic.
        topic = set(
            tokenize(" ".join(w for w in _WORDS.findall(focus) if w.lower() not in FILLER_WORDS))
        )
        topic |= {alias for term in topic for alias in related_terms(term)}
        returned = set().union(
            *(
                set(tokenize(b.get("source", ""))) | set(tokenize(b["symbol"] or ""))
                for b in shown[:2]
            )
        )
        if topic and not topic & returned:
            level = "low"
    if not shown and not literals:
        level = "low"
    graph_led = bool(shown and shown[0]["role"] in ("graphify hint", "similar"))
    if graph_led:
        # Likewise for a block only the embedding model found: a candidate, never a proof.
        # Verified locations are useful candidates even without lexical source
        # hits, but an imported relationship cannot justify high confidence.
        level = "medium"
    pack["confidence"] = level
    stale = bool(pack["stale_sources"])
    # With a checked patch the code beside the sites is context, so an excerpt is not a gap.
    top_cut = bool(shown and shown[0]["truncated"]) and not pack.get("patch")
    pack["sufficient"] = (
        level == "high"
        and not stale
        and not top_cut
        and not incomplete_literals
        and not evidence.limited
    )
    if stale:
        pack["next"] = "Index is behind the source: run prism update, then ask again."
    elif level == "low":
        pack["next"] = "Weak match: use grep for the exact strings before editing."
    elif level == "medium":
        pack["next"] = (
            "Candidates only: confirm against the request; search other wording if a spot is missing."
        )
    elif evidence.limited:
        pack["next"] = (
            "Exact-match search is incomplete: use targeted search for omitted candidates before editing."
        )
    elif incomplete_literals:
        pack["next"] = (
            "Some literal matches were omitted: increase the budget or grep before editing."
        )
    elif top_cut:
        pack["next"] = (
            "Source is partial: request a larger budget or read the remaining lines before editing."
        )
    elif literals:
        listed = [lit for lit in literals if lit["complete"] and lit["kind"] != "identifier"]
        if pack.get("patch"):
            pack["next"] = (
                "Mechanical change: apply the patch above, then run the listed tests; "
                "hand-edit only sites needing different wording."
            )
        elif listed:
            sites = sum(len(lit["occurrences"]) for lit in listed)
            files = len({o["file"] for lit in listed for o in lit["occurrences"]})
            pack["next"] = (
                f"Edit-ready: {sites} listed sites in {files} files are exhaustive; edit them "
                "now, no repo-wide search. Run the listed tests."
            )
        else:
            pack["next"] = (
                "Literal lists are exhaustive over the indexed source: edit from them without "
                "re-grepping; run the listed tests."
            )
    else:
        pack["next"] = "Edit from these locations; check the callers listed; run the listed tests."
    if evidence.absent and level != "low" and len(pack["next"]) <= NEXT_RESERVE - 38:
        pack["next"] += " Names listed as new do not exist yet."
    assert len(pack["next"]) <= NEXT_RESERVE, pack["next"]


def _safely(fn: Any, *args: Any) -> Any:
    """An enricher is optional: whatever goes wrong inside it, the packet is still built."""
    try:
        return fn(*args)
    except Exception:
        return None


def _drop_graph_lines(pack: dict[str, Any]) -> None:
    """Keep the tests, drop callers, callees and impact (a patch or a brief packet needs no map)."""
    links = [link for link in pack.get("links", []) if link["role"] == "test"]
    if links:
        pack["links"] = links
    else:
        pack.pop("links", None)
    pack.pop("callers_omitted", None)
    pack.pop("impact", None)


def _offer(
    pack: dict[str, Any], key: str, value: Any, budget: int, room_from_blocks: bool = False
) -> None:
    """Add an optional packet field only if the packet still fits its budget.

    With `room_from_blocks`, the lowest-ranked code blocks (never the first two) may be dropped to
    make it fit: a line that prevents a wrong or missed edit outweighs a third code excerpt."""
    pack[key] = value
    while _size(pack) > budget and room_from_blocks and len(pack["blocks"]) > 2:
        pack["blocks"].pop()
    if _size(pack) > budget:
        del pack[key]


def _enrich(
    store: IndexStore,
    reader: SourceReader,
    pack: dict[str, Any],
    primaries: list[SymbolRow],
    budget: int,
) -> None:
    """Twins, read ranges, batching and the done condition, each only when it fits."""
    twins = _safely(enrich.find_twins, store, reader, primaries)
    if twins:
        _offer(pack, "twins", twins, budget, room_from_blocks=True)

    sites: dict[str, list[int]] = {}
    for lit in pack.get("literals", []):
        if lit["kind"] == "identifier" and not lit["complete"]:
            continue
        for occ in lit["occurrences"]:
            sites.setdefault(occ["file"], []).append(occ["line"])
    for block in pack["blocks"]:
        if block.get("source"):
            sites.setdefault(block["file"], []).append(block["lines"][0])
    for twin in pack.get("twins", []):
        for copy_ in twin["copies"]:
            sites.setdefault(copy_["file"], []).append(copy_["lines"][0])
    if not pack.get("patch"):  # a patch already applies every site in one call
        ranges = _safely(enrich.read_ranges, reader, sites)
        if ranges:
            _offer(pack, "read_ranges", ranges, budget)
        editable = {f for f in sites if not store._is_test(f)}
        if len(editable) >= 2:
            _offer(pack, "batch", len(editable), budget)

    if pack.get("patch"):
        done = "git apply succeeded, the listed tests pass"
    elif any(lit["complete"] and lit["kind"] != "identifier" for lit in pack.get("literals", [])):
        done = "every listed site is changed (`--mode verify` confirms none remain)"
    elif pack.get("run"):
        done = "the listed tests pass"
    else:
        done = ""
    if done:
        _offer(pack, "done", done, budget)
    if (
        pack.get("twins")
        and not pack.get("patch")
        and pack["confidence"] != "low"
        and not pack["stale_sources"]
    ):
        pack["next"] = (
            "Change every copy listed under Twins, not only the first; run the listed tests."
        )
