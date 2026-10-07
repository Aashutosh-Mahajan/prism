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
from dataclasses import dataclass, field
from typing import Any

from prism.core.errors import UserError
from prism.core.tokens import estimate_tokens
from prism.navigator.impact import dependents
from prism.navigator.literals import EvidenceResult, find_literals
from prism.navigator.resolve import Target
from prism.navigator.source_index import SourceIndex, SourceReader
from prism.navigator.store import IndexStore, SymbolRow
from prism.navigator.synonyms import EXPANSION_WEIGHT, related_terms
from prism.navigator.text import FILLER_WORDS, tokenize

MIN_BUDGET, MAX_BUDGET = 128, 32000
WHOLE_SYMBOL_MAX = 50  # lines; a larger symbol is shown as windows around the matching lines
WINDOW_PAD = 2
MERGE_GAP = 5
MAX_BLOCKS = 6
MAX_PER_FILE = 2
MAX_FILE_CANDIDATES = 25
MAX_HITS_PER_FILE = 8
MAX_CALLERS = 6
MAX_STRUCTURAL_CALLERS = 12
MAX_TESTS = 3
MIN_TEST_NAME = 5  # shorter names (get, post, run) would match every test
NEXT_RESERVE = 150  # characters set aside for the closing `next` guidance
LITERAL_SHARE = 0.40
LITERAL_WIDTHS = (110, 80, 56)  # snippet widths tried, widest first
EXPLICIT_BONUS = 60.0  # a symbol or file the request names outright
MENTIONED_BONUS = 25.0  # a code-like name in the request that resolves to one or two symbols
CODE_KINDS = ("function", "method", "class")
TEST_DEMOTION = 0.5
MIGRATION_DEMOTION = 0.35
DOC_DEMOTION = 0.4
DOC_DIRS = frozenset(["docs", "doc", "documentation"])
HEADER_PENALTY = 0.35  # imports and the module docstring match words without being the answer
HIGH_MARGIN = 2.2  # best block this many times the next: a clear winner
MEDIUM_MARGIN = 1.5
PATH_BONUS = 0.7  # share of a path word's weight given to every block in that file
NAME_BONUS = 1.5  # share of a symbol-name word's weight added to its blocks
NEW_NAME_WEIGHT = 0.5  # words that only occur in names the request says are new
REINFORCE = 0.25  # share of a neighbouring block's score a caller/callee block earns
MIN_RELATIVE_SCORE = 0.25  # blocks scoring below this share of the best are noise
# When exact literal evidence is complete it already answers "where"; code beside it is only
# context, so fewer and stronger blocks are shown.
TIGHT_RELATIVE_SCORE = 0.5
TIGHT_MAX_BLOCKS = 3
_IMPORT_LINE = re.compile(r"^\s*(?:import|from|package|using|require)|^\s*#include")

_WORDS = re.compile(r"[A-Za-z0-9]+")
_STRUCTURAL = re.compile(
    r"\b(?:who|what|which)\s+(?:calls|uses|depends|imports)\b|\bcallers?\s+of\b"
    r"|\bwhere\s+(?:is|are)\b[^?]*\bused\b|\busages?\s+of\b|\bimpact\s+of\b"
    r"|\bwhat\s+(?:breaks|would\s+break|will\s+break)\b|\bblast\s+radius\b"
    r"|\btests?\s+(?:for|covering)\b",
    re.IGNORECASE,
)
_LOCATE = re.compile(r"^\s*(?:where\s+is|which\s+file|find|locate)\b", re.IGNORECASE)


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
    for lit in pack.get("literals", []):
        shown = len(lit["occurrences"])
        scope = "exhaustive" if lit["complete"] else f"{shown} of {lit['total']} shown"
        parts.append(f'Literal "{lit["text"]}" ({lit["kind"]}, {lit["total"]} found, {scope}):')
        parts.extend(f"  {_loc(o['file'], o['line'])}: {o['text']}" for o in lit["occurrences"])
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
            head += " [excerpt; inspect remaining code before editing]"
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
    if tests:
        parts.append("Tests: " + ", ".join(tests))
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
    if not pack["blocks"] and not pack.get("literals"):
        parts.append("No source fits or matches; refine the query or increase the budget.")
    parts.append(f"Next: {pack['next']}")
    return "\n".join(parts)


def _size(pack: dict[str, Any]) -> int:
    # Reserve digits for the final estimate itself. Includes JSON keys/escaping, source
    # line numbers, graph links and Markdown. MCP transport envelopes are host overhead.
    pack["budget"]["used_est"] = 999999
    return max(
        estimate_tokens(json.dumps(pack, indent=2, ensure_ascii=False)),
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
        top = sorted((hits[line] for line in lines), reverse=True)[:5]
        score = sum(top) + prior
        if sym is not None:
            name_terms = set(tokenize(sym.name))
            score += NAME_BONUS * sum(terms.get(t, 0.0) for t in name_terms)
        reported = all((file, line) in explained for line in lines)
        if sym is not None and sym.end - sym.start + 1 <= WHOLE_SYMBOL_MAX and not reported:
            blocks.append(_Block(file, sym.start, sym.end, sym, score, lines, whole=True))
            continue
        for lo, hi in _windows(lines, total):
            inside = [line for line in lines if lo <= line <= hi]
            local = sum(sorted((hits[line] for line in inside), reverse=True)[:5]) + prior
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
) -> dict[str, Any]:
    if not MIN_BUDGET <= budget <= MAX_BUDGET:
        raise UserError(
            f"task budget must be between {MIN_BUDGET} and {MAX_BUDGET} (chars/4 estimate)"
        )
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
    with SourceIndex(store) as index:
        _fill(store, index, query, budget, seen, pack)
    return pack


def _fill(
    store: IndexStore,
    index: SourceIndex,
    query: str,
    budget: int,
    seen: set[tuple[str, int, int]] | None,
    pack: dict[str, Any],
) -> None:
    reader = SourceReader(store)
    terms = _query_terms(query, index)
    evidence = find_literals(index, reader, query)
    exact_symbol = store.symbol(query)
    named = store.symbols_named(query) if query.isidentifier() else []
    exact_file = query if store.file_exists(query) else None
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
    prior: dict[str, float] = {}
    for rank, (file, _) in enumerate(ranked):
        prior[file] = 1.0 / (1 + rank)
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
            prior[hit_file] = prior.get(hit_file, 0.0) + 0.3
    literal_lines = evidence.hit_lines()
    for file, _ in literal_lines:
        prior.setdefault(file, 0.2)
    definitions = _definitions(store, query, evidence, exact_symbol, named, exact_file)
    for block in definitions:
        prior.setdefault(block.file, 0.5)
    candidates = sorted(prior, key=lambda f: (-prior[f], f))[: MAX_FILE_CANDIDATES + 10]

    max_weight = max(terms.values(), default=0.0)
    blocks: list[_Block] = list(definitions)
    matched_terms: dict[str, set[str]] = {}
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
                matched_terms.setdefault(file, set()).update(matched)
        if not hits:
            continue
        top = dict(sorted(hits.items(), key=lambda kv: -kv[1])[:MAX_HITS_PER_FILE])
        blocks.extend(
            _group_blocks(
                file, top, symbols, len(lines), terms, prior[file] + path_bonus, explained
            )
        )
    pack["stale_sources"] = len(reader.stale)
    wants_tests = any(t.startswith("test") or t == "spec" for t in terms)
    wants_migrations = any(t.startswith("migrat") for t in terms)
    wants_docs = any(t in ("doc", "docs", "document", "documentation", "readme") for t in terms)
    for block in blocks:
        # Application code is what gets changed; tests and generated migrations rank below it
        # unless the request is about them (the same rule `prism search` applies).
        if not wants_tests and store._is_test(block.file):
            block.score *= TEST_DEMOTION
        elif not wants_migrations and "/migrations/" in f"/{block.file}":
            block.score *= MIGRATION_DEMOTION
        elif not wants_docs and block.file.split("/", 1)[0] in DOC_DIRS:
            block.score *= DOC_DEMOTION
    _reinforce(store, blocks)
    blocks = _select(blocks, tight=any(lit.complete for lit in evidence.literals))
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
                store._is_test(o.file) or o.file.split("/", 1)[0] in DOC_DIRS,
                -prior.get(o.file, 0.0),
                o.file,
                o.line,
            )
        )
        placed = False
        for width in LITERAL_WIDTHS:  # a narrower snippet beats a missing occurrence
            literals.append(ev.to_dict(width))
            if _size(pack) <= literal_budget:
                placed = True
                break
            literals.pop()
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
    _fit_blocks(pack, blocks, reader, budget, seen, structural)

    primaries = _primaries(pack, blocks)
    if primaries:
        _links(store, index, reader, pack, primaries, budget, structural)
    _confidence(pack, evidence, blocks, matched_terms, terms, exact)
    pack["budget"]["used_est"] = _size(pack)


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
) -> None:
    placed = 0
    for rank, block in enumerate(blocks):
        if placed >= MAX_BLOCKS:
            break
        lines = reader.lines(block.file)
        if not lines:
            continue
        start, end = block.start, min(block.end, len(lines))
        if structural and rank == 0:
            end = min(end, start + 24)
        key = (block.file, start, end)
        sym_id = block.symbol.id if block.symbol else None
        if seen is not None and key in seen:
            pack["blocks"].append(
                {
                    "role": block.role,
                    "file": block.file,
                    "symbol": sym_id,
                    "lines": [start, end],
                    "truncated": False,
                    "seen": True,
                }
            )
            if _size(pack) > budget:
                pack["blocks"].pop()
            placed += 1
            continue
        share = int(budget * (0.45 if rank == 0 else 0.25))
        full_start, full_end = start, end
        focus = block.hits[0] if block.hits else start
        while start <= end:
            item = {
                "role": block.role,
                "file": block.file,
                "symbol": sym_id,
                "lines": [start, end],
                "truncated": start != full_start or end != full_end,
                "source": _render_source(lines, start, end),
            }
            before = _size(pack)
            pack["blocks"].append(item)
            size = _size(pack)
            if size <= budget and size - before <= share:
                placed += 1
                if seen is not None:
                    seen.add((block.file, full_start, full_end))
                break
            pack["blocks"].pop()
            # Shrink away from the matching lines first, keeping the focus visible.
            if end - focus >= focus - start:
                end -= 1
            else:
                start += 1


def _primaries(pack: dict[str, Any], blocks: list[_Block], limit: int = 2) -> list[SymbolRow]:
    """The symbols the answer is about: the first code symbols among the blocks, best first."""
    shown = {(b["file"], tuple(b["lines"])) for b in pack["blocks"]}
    candidates = [
        b for b in blocks if b.symbol is not None and (b.file, (b.start, b.end)) in shown
    ] or [b for b in blocks if b.symbol is not None]
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
    direct = store.tests_for_symbol(symbol.id)
    if direct:
        return direct[:MAX_TESTS]
    found: list[str] = []
    name_tokens = tokenize(symbol.name)
    if len(symbol.name) >= MIN_TEST_NAME and name_tokens:
        mentions = [f for f in index.files_with_all(name_tokens) if store._is_test(f)]
        found.extend(sorted(mentions, key=lambda f: (_common_prefix(f, symbol.file) * -1, f)))
    if len(found) < MAX_TESTS:
        imported = sorted(
            store.tests_for_file(symbol.file),
            key=lambda f: (_common_prefix(f, symbol.file) * -1, f),
        )
        found.extend(f for f in imported[:2] if f not in found)
    return found[:MAX_TESTS]


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
    for number, primary in enumerate(primaries):
        limit = MAX_STRUCTURAL_CALLERS if structural else MAX_CALLERS
        if len(primaries) > 1:
            limit = max(3, limit // 2)
        callers = store.callers(primary.id)
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
    for path in _related_tests(store, index, first):
        add({"role": "test", "file": path})
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
    parts = set(tokenize(blocks[0].symbol.name))
    return len(parts) >= 2 and all(p in terms for p in parts)


def _confidence(
    pack: dict[str, Any],
    evidence: EvidenceResult,
    blocks: list[_Block],
    matched_terms: dict[str, set[str]],
    terms: dict[str, float],
    exact: bool,
) -> None:
    shown = list(pack["blocks"])
    total = sum(terms.values())
    coverage = 0.0
    for b in shown[:2]:
        got = matched_terms.get(b["file"], set()) | {
            t for t in terms if t in set(tokenize(b["file"]))
        }
        if total:
            coverage = max(coverage, sum(terms[t] for t in got if t in terms) / total)
    literals = pack.get("literals", [])
    exhaustive = any(lit["complete"] for lit in literals)
    margin = _margin(blocks)
    named = _named_by_request(blocks, terms)
    if exact or exhaustive or coverage >= 0.55 or margin >= HIGH_MARGIN:
        level = "high"
    elif coverage >= 0.3 or literals or margin >= MEDIUM_MARGIN or named:
        level = "medium"
    else:
        level = "low"
    if not shown and not literals:
        level = "low"
    pack["confidence"] = level
    stale = bool(pack["stale_sources"])
    top_cut = bool(shown and shown[0]["truncated"])
    pack["sufficient"] = level == "high" and not stale and not top_cut
    if stale:
        pack["next"] = "Index is behind the source: run prism update, then ask again."
    elif level == "low":
        pack["next"] = "Weak match: use grep for the exact strings before editing."
    elif level == "medium":
        pack["next"] = (
            "Candidates only: confirm against the request; search other wording if a spot is missing."
        )
    elif literals:
        pack["next"] = (
            "Literal lists are exhaustive over the indexed source: edit from them without "
            "re-grepping; run the listed tests."
        )
    else:
        pack["next"] = "Edit from these locations; check the callers listed; run the listed tests."
    if evidence.absent and level != "low" and len(pack["next"]) <= NEXT_RESERVE - 38:
        pack["next"] += " Names listed as new do not exist yet."
    assert len(pack["next"]) <= NEXT_RESERVE, pack["next"]
