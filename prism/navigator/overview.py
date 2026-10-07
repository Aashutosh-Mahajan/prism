"""Query-focused repository maps: signatures and relationships, never source dumps.

Independent implementation of the repository-map/progressive-disclosure ideas
documented by Aider and Serena. No upstream code or runtime dependency is used.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from typing import Any

from prism.navigator.source_index import SourceReader
from prism.navigator.store import IndexStore, ModuleRow, SymbolRow
from prism.navigator.text import FILLER_WORDS, tokenize

_BROAD = re.compile(
    r"\b(?:overview|onboard(?:ing)?|orient(?:ation)?|architecture|codebase\s+map|repo(?:sitory)?\s+map)\b"
    r"|\bunderstand\b.*\b(?:project|repo(?:sitory)?|codebase)\b",
    re.IGNORECASE,
)
_EDIT = re.compile(r"\b(?:fix|change|rename|implement|add|remove|replace|update|refactor)\b", re.I)
_MAP_WORDS = frozenset(
    {
        "overview",
        "onboard",
        "orientation",
        "architecture",
        "understand",
        "project",
        "repo",
        "repository",
        "codebase",
        "map",
        "entry",
        "point",
        "subsystem",
        "relevant",
        "especially",
        "existing",
        "main",
        "function",
        "caller",
        "test",
    }
)
MAX_FILES = 12
MAX_SYMBOLS = 6


def wants_overview(query: str) -> bool:
    return bool(_BROAD.search(query) and not _EDIT.search(query))


def overview_items(store: IndexStore, reader: SourceReader, query: str) -> dict[str, Any]:
    """Return bounded candidates; the task assembler fits every row to its budget."""
    terms = {
        term
        for word in re.findall(r"[A-Za-z0-9]+", query)
        if word.lower() not in FILLER_WORDS
        for term in tokenize(word)
        if word.lower() not in _MAP_WORDS
    }
    exact_files = store.files_with_suffix(query.strip())
    modules = [m for m in store.modules() if not store._is_test(m.file)]
    exact = set(exact_files)
    scores: dict[str, float] = {}
    for module in modules:
        overlap = len(terms & set(tokenize(module.id + " " + module.doc)))
        scores[module.file] = overlap * 10.0 + (100.0 if module.file in exact else 0.0)
    for hit in store.search(" ".join(sorted(terms)), 24) if terms else []:
        if hit.kind == "symbol":
            symbol = store.symbol(hit.ref)
            if symbol and symbol.file in scores:
                scores[symbol.file] += 3.0
    ranked = sorted(
        modules, key=lambda m: (-scores[m.file], not bool(m.entry_point), -m.rank, m.file)
    )
    if terms:
        ranked = [m for m in ranked if scores[m.file] > 0]
    selected: list[ModuleRow] = []
    # Global maps represent distinct directories before taking more files from
    # a central package; PageRank alone can let one utility own the whole map.
    seen_dirs: set[str] = set()
    for module in ranked:
        directory = module.file.rsplit("/", 1)[0] if "/" in module.file else "."
        if not terms and directory in seen_dirs:
            continue
        selected.append(module)
        seen_dirs.add(directory)
        if len(selected) == MAX_FILES:
            break
    for module in ranked:
        if module not in selected and len(selected) < MAX_FILES:
            selected.append(module)
    # Exact-file maps can include a test or an unparsed language too.
    selected_files = list(dict.fromkeys([*sorted(exact), *(m.file for m in selected)]))[:MAX_FILES]
    rows: list[dict[str, Any]] = []
    relevant_symbols: list[SymbolRow] = []
    for file in selected_files:
        if reader.lines(file) is None:
            continue
        symbols = store.symbols_in_file(file)
        file_module = store.module_for_file(file)
        ordered = sorted(
            symbols,
            key=lambda s: (
                -len(terms & set(tokenize(s.name + " " + s.doc))),
                not bool(file_module and file_module.entry_point and s.name.lstrip("_") == "main"),
                s.parent is not None,
                s.visibility != "public",
                -(s.rank * (1.0 + min(100, s.end - s.start + 1) / 100)),
                s.start,
                s.id,
            ),
        )
        chosen = ordered[:MAX_SYMBOLS]
        relevant_symbols.extend(chosen)
        rows.append(
            {
                "file": file,
                "entry": file_module.entry_point if file_module else None,
                "symbols": [
                    {"id": s.id, "lines": [s.start, s.end], "signature": s.signature[:180]}
                    for s in chosen
                ],
                "symbols_omitted": max(0, len(symbols) - len(chosen)),
            }
        )
    links: list[dict[str, Any]] = []
    seen_links: set[tuple[str, str, int | None]] = set()
    for symbol in relevant_symbols[: MAX_FILES * MAX_SYMBOLS]:
        for caller in store.callers(symbol.id):
            key = (caller.symbol.id, symbol.id, caller.line)
            if key in seen_links or caller.confidence == "low":
                continue
            seen_links.add(key)
            links.append(
                {
                    "from": caller.symbol.id,
                    "to": symbol.id,
                    "file": caller.symbol.file,
                    "line": caller.line,
                    "confidence": caller.confidence,
                    "relation": "calls",
                }
            )
            if len(links) >= 20:
                break
        if len(links) >= 20:
            break
    selected_modules = {m.id: m for m in selected if m.file in {row["file"] for row in rows}}
    # Import links cover architecture layers even when framework dispatch or
    # dependency injection prevents a confident static call edge.
    imports: list[dict[str, Any]] = []
    for mid in sorted(selected_modules):
        for target in store.imports_of(mid):
            if target in selected_modules:
                imports.append(
                    {
                        "from": mid,
                        "to": target,
                        "file": selected_modules[mid].file,
                        "line": None,
                        "confidence": "high",
                        "relation": "imports",
                    }
                )
            if len(imports) >= 12:
                break
        if len(imports) >= 12:
            break
    links = imports[:6] + links
    tests = sorted({test for file in selected_files for test in store.tests_for_file(file)})[:5]
    if not tests:
        tests = sorted(store.test_files())[:3]
    external = Counter(
        name.split(".", 1)[0]
        for module in selected
        for name in store.externals_of(module.id)
        if name.split(".", 1)[0] not in sys.stdlib_module_names
    )
    return {
        "languages": store.manifest.get("stats", {}).get("languages", {}),
        "dependencies": [
            name for name, _ in sorted(external.items(), key=lambda p: (-p[1], p[0]))[:8]
        ],
        "files": rows,
        "links": links,
        "tests": tests,
        "files_total": len(store.manifest.get("files", {})),
        "symbols_total": store.manifest.get("stats", {}).get("symbols", 0),
    }


def render_overview(overview: dict[str, Any]) -> list[str]:
    lines = [f"Map: {overview['files_total']} indexed files · {overview['symbols_total']} symbols"]
    languages = overview.get("languages", {})
    if languages:
        lines.append(
            "Languages: "
            + ", ".join(f"{name} ({count})" for name, count in sorted(languages.items()))
        )
    if overview.get("dependencies"):
        lines.append("Imports outside stdlib: " + ", ".join(overview["dependencies"]))
    for file in overview.get("files", []):
        lines.append(file["file"] + (f" [entry: {file['entry']}]" if file.get("entry") else ""))
        for symbol in file["symbols"]:
            lines.append(
                f"  {symbol['lines'][0]}-{symbol['lines'][1]}: {symbol['signature']} ({symbol['id']})"
            )
        if file["symbols_omitted"]:
            lines.append(f"  +{file['symbols_omitted']} symbols omitted")
    if overview.get("links"):
        lines.append("Static relationships (not runtime proof):")
        for link in overview["links"]:
            lines.append(
                f"  {link['from']} --{link['relation']}--> {link['to']} ({link['file']}:{link['line'] or 0}, {link['confidence']})"
            )
    if overview.get("tests"):
        lines.append("Related test candidates: " + ", ".join(overview["tests"]))
    if overview.get("omitted"):
        lines.append(
            "Map is selective; omitted rows are not missing files. Ask for a file/symbol to read its code."
        )
    return lines
