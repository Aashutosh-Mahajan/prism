"""`prism locate` and target resolution for `context` / `impact`.

Resolution order: exact id -> qualified suffix -> file path -> fuzzy name.
Ambiguity is always reported as a ranked candidate list, never guessed.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Any, Literal

from prism.core.errors import AmbiguousTargetError, NotFoundError
from prism.navigator.store import IndexStore, ModuleRow, SymbolRow

HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "ANY")
_ROUTE = re.compile(rf"^({'|'.join(HTTP_METHODS)})\s+(/\S*)$", re.IGNORECASE)
_FILE_LINE = re.compile(r"^(.+?):(\d+)$")

Match = Literal["exact", "suffix", "file", "module", "fuzzy"]
_TIER: dict[str, int] = {"exact": 0, "suffix": 1, "file": 2, "module": 3, "fuzzy": 4}


@dataclass(frozen=True)
class Candidate:
    id: str
    kind: str
    file: str
    lines: tuple[int, int] | None
    signature: str
    match: Match
    rank: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "file": self.file,
            "lines": list(self.lines) if self.lines else None,
            "signature": self.signature,
            "match": self.match,
        }


@dataclass(frozen=True)
class Target:
    kind: Literal["symbol", "module", "file"]
    file: str
    symbol: SymbolRow | None = None
    module: ModuleRow | None = None
    route: str | None = None

    @property
    def id(self) -> str:
        if self.symbol:
            return self.symbol.id
        if self.module:
            return self.module.id
        return self.file


def _sym_candidate(s: SymbolRow, match: Match) -> Candidate:
    return Candidate(s.id, s.kind, s.file, s.lines, s.signature, match, s.rank)


def locate(store: IndexStore, name: str, limit: int = 10) -> list[Candidate]:
    name = name.strip()
    found: dict[str, Candidate] = {}

    def add(c: Candidate) -> None:
        prev = found.get(c.id)
        if prev is None or _TIER[c.match] < _TIER[prev.match]:
            found[c.id] = c

    exact = store.symbol(name)
    if exact:
        add(_sym_candidate(exact, "exact"))
    mod = store.module(name)
    if mod:
        add(Candidate(mod.id, "module", mod.file, None, "", "exact", mod.rank))
    if not found:
        for s in store.symbols_with_suffix(name):
            add(_sym_candidate(s, "suffix"))
        for path in store.files_with_suffix(name):
            m = store.module_for_file(path)
            add(
                Candidate(path, "file", path, None, m.id if m else "", "file", m.rank if m else 0.0)
            )
        for m in store.modules():
            if m.id.endswith("." + name) or m.id.rsplit(".", 1)[-1] == name:
                add(Candidate(m.id, "module", m.file, None, "", "module", m.rank))
    if not found:
        leaf = name.rsplit(".", 1)[-1]
        for close in difflib.get_close_matches(leaf, store.symbol_names(), n=5, cutoff=0.75):
            for s in store.symbols_named(close):
                add(_sym_candidate(s, "fuzzy"))
    ranked = sorted(found.values(), key=lambda c: (_TIER[c.match], -c.rank, c.id))
    return ranked[:limit]


def _suggestions(store: IndexStore, text: str) -> list[str]:
    leaf = re.split(r"[./:\\]", text)[-1] or text
    return difflib.get_close_matches(leaf, store.symbol_names(), n=5, cutoff=0.6)


def resolve_target(store: IndexStore, text: str) -> Target:
    text = text.strip()
    route = _ROUTE.match(text)
    if route:
        method, path = route.group(1).upper(), route.group(2)
        for r in store.routes():
            if r["path"] == path and r["method"] in (method, "ANY"):
                sym = store.symbol(r["handler"])
                if sym:
                    return Target("symbol", sym.file, symbol=sym, route=f"{method} {path}")
        raise NotFoundError(
            f"no route matches '{method} {path}'",
            suggestions=[f"{r['method']} {r['path']}" for r in store.routes()[:10]],
        )

    file_line = _FILE_LINE.match(text)
    if file_line and not store.symbol(text):
        files = store.files_with_suffix(file_line.group(1))
        if len(files) == 1:
            line = int(file_line.group(2))
            sym = store.symbol_at(files[0], line)
            if sym:
                return Target("symbol", sym.file, symbol=sym)
            return Target("file", files[0], module=store.module_for_file(files[0]))
        if len(files) > 1:
            raise AmbiguousTargetError(
                f"'{file_line.group(1)}' matches several files", candidates=files[:10]
            )

    sym = store.symbol(text)
    if sym:
        return Target("symbol", sym.file, symbol=sym)
    if "/" in text or text.endswith(".py") or store.file_exists(text):
        files = store.files_with_suffix(text)
        if len(files) == 1:
            return Target("file", files[0], module=store.module_for_file(files[0]))
        if len(files) > 1:
            raise AmbiguousTargetError(f"'{text}' matches several files", candidates=files[:10])
    mod = store.module(text)
    if mod:
        return Target("module", mod.file, module=mod)

    candidates = locate(store, text)
    if not candidates:
        raise NotFoundError(f"nothing matches '{text}'", suggestions=_suggestions(store, text))
    best_tier = _TIER[candidates[0].match]
    if best_tier == _TIER["fuzzy"]:
        raise NotFoundError(
            f"nothing matches '{text}'; did you mean one of the suggestions?",
            suggestions=[c.id for c in candidates],
        )
    top = [c for c in candidates if _TIER[c.match] == best_tier]
    if len(top) > 1:
        raise AmbiguousTargetError(
            f"'{text}' is ambiguous; pass one of the candidate ids",
            candidates=[c.to_dict() for c in candidates],
        )
    only = top[0]
    if only.kind == "file":
        return Target("file", only.file, module=store.module_for_file(only.file))
    if only.kind == "module":
        m = store.module(only.id)
        assert m is not None
        return Target("module", m.file, module=m)
    s = store.symbol(only.id)
    assert s is not None
    return Target("symbol", s.file, symbol=s)
