"""`prism find`: several searches in one call, grouped, ranked and within a token budget.

An agent that needs three greps pays for three model calls, each carrying the whole conversation.
This answers them together over the indexed code and the text/data files (translations, config,
docs). Matching is by substring, like `grep -F`, or by regular expression with `--regex`.
"""

from __future__ import annotations

import fnmatch
import re
from typing import Any

from prism.core.errors import UserError
from prism.core.tokens import estimate_tokens
from prism.navigator.enrich import scope_factor
from prism.navigator.source_index import SourceIndex, SourceReader
from prism.navigator.store import IndexStore

DEFAULT_BUDGET = 1500
MAX_PATTERNS = 8
MAX_MATCHES_PER_PATTERN = 400  # scanning stops here and the result says so
LINE_WIDTH = 150


def _compile(pattern: str, regex: bool, ignore_case: bool) -> re.Pattern[str]:
    flags = re.IGNORECASE if ignore_case else 0
    try:
        return re.compile(pattern if regex else re.escape(pattern), flags)
    except re.error as exc:
        raise UserError(f"bad regular expression {pattern!r}: {exc}") from exc


def _width(line: str, col: int) -> str:
    line = " ".join(line.split())
    if len(line) <= LINE_WIDTH:
        return line
    start = max(0, min(col - LINE_WIDTH // 3, len(line) - LINE_WIDTH))
    piece = line[start : start + LINE_WIDTH]
    return ("…" if start else "") + piece + ("…" if start + LINE_WIDTH < len(line) else "")


def run_find(
    store: IndexStore,
    patterns: list[str],
    regex: bool = False,
    ignore_case: bool = False,
    globs: list[str] | None = None,
    budget: int = DEFAULT_BUDGET,
) -> dict[str, Any]:
    patterns = [p for p in patterns if p.strip()]
    if not patterns:
        raise UserError("give at least one pattern: prism find 'name' 'other text'")
    if len(patterns) > MAX_PATTERNS:
        raise UserError(f"at most {MAX_PATTERNS} patterns per call")
    if not 128 <= budget <= 32000:
        raise UserError("find budget must be between 128 and 32000")
    compiled = [_compile(p, regex, ignore_case) for p in patterns]
    globs = globs or []

    found: list[list[tuple[str, int, str]]] = [[] for _ in patterns]
    complete = [True] * len(patterns)
    query = " ".join(patterns)
    with SourceIndex(store) as index:
        reader = SourceReader(store)
        reader.corpus = index.text
        files = sorted(set(store.all_files()) | set(index.text.paths))
        if globs:
            files = [f for f in files if any(fnmatch.fnmatch(f, g) for g in globs)]
        for file in files:
            lines = reader.lines(file)
            if not lines:
                continue
            for number, line in enumerate(lines, 1):
                for i, pattern in enumerate(compiled):
                    if len(found[i]) >= MAX_MATCHES_PER_PATTERN:
                        complete[i] = False
                        continue
                    m = pattern.search(line)
                    if m:
                        found[i].append((file, number, _width(line, m.start())))

    results: list[dict[str, Any]] = []
    for text, matches, whole in zip(patterns, found, complete, strict=True):
        by_file: dict[str, list[tuple[int, str]]] = {}
        for file, number, shown in matches:
            by_file.setdefault(file, []).append((number, shown))
        order = sorted(
            by_file,
            key=lambda f: (
                store._is_test(f) or scope_factor(query, f) < 1.0 or "/migrations/" in f"/{f}",
                f,
            ),
        )
        results.append(
            {
                "pattern": text,
                "total": len(matches),
                "files": len(by_file),
                "complete": whole,
                "matches": [
                    {"file": f, "lines": [{"line": n, "text": t} for n, t in by_file[f]]}
                    for f in order
                ],
            }
        )
    pack: dict[str, Any] = {
        "intent": "find",
        "results": results,
        "omitted": 0,
        "budget": {"requested": budget, "used_est": 0, "estimator": "ceil(chars/4)"},
    }
    _fit(pack, budget)
    return pack


def _size(pack: dict[str, Any]) -> int:
    pack["budget"]["used_est"] = 999999
    return estimate_tokens(render_find(pack))


def _fit(pack: dict[str, Any], budget: int) -> None:
    """Drop the lowest-ranked lines (last file of the pattern with most lines) until it fits."""
    while _size(pack) > budget:
        victim = max(
            (r for r in pack["results"] if r["matches"]),
            key=lambda r: sum(len(m["lines"]) for m in r["matches"]),
            default=None,
        )
        if victim is None:
            break
        last = victim["matches"][-1]
        last["lines"].pop()
        pack["omitted"] += 1
        if not last["lines"]:
            victim["matches"].pop()
    pack["budget"]["used_est"] = _size(pack)


def render_find(pack: dict[str, Any]) -> str:
    out = [
        f"PRISM find · {len(pack['results'])} pattern(s) · "
        f"{pack['budget']['used_est']}/{pack['budget']['requested']} est. tokens"
    ]
    for result in pack["results"]:
        shown = sum(len(m["lines"]) for m in result["matches"])
        state = (
            "exhaustive"
            if result["complete"] and shown == result["total"]
            else (
                f"{shown} of {'at least ' if not result['complete'] else ''}{result['total']} shown"
            )
        )
        out.append(f'"{result["pattern"]}": {result["total"]} in {result["files"]} files ({state})')
        for match in result["matches"]:
            out.append(f"  {match['file']}")
            out.extend(f"    {item['line']}: {item['text']}" for item in match["lines"])
    out.append(
        "Next: lines shown are exact; edit from them without re-searching."
        if not pack["omitted"] and all(r["complete"] for r in pack["results"])
        else "Next: some lines were omitted for the budget; raise --budget or narrow with --glob."
    )
    return "\n".join(out)
