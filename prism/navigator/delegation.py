"""Follow thin delegating wrappers to the code that holds the behaviour.

Real code is layered: a public facade method calls a factory, which constructs the class whose
method does the work. A request phrased in the facade's terms matches the facade; the edit
belongs further in. This module walks the *call graph* from such wrappers to the first symbol
with a real body. It knows nothing about any language or framework, only that a symbol with a
tiny body whose calls resolve to project symbols is a wrapper.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from prism.navigator.store import IndexStore, SymbolRow
from prism.navigator.text import tokenize

THIN_SPAN = 5  # lines, signature included: `def f(...)` plus a body of one or two statements
MAX_DEPTH = 3  # wrapper hops; a longer chain is architecture, not a wrapper
MAX_FANOUT = 3  # callees followed from one wrapper; a hub is not a delegation
MAX_TARGETS = 3
TRUSTED = frozenset(["high", "medium"])
CODE = frozenset(["function", "method", "class"])
# Verbs and glue that tie unrelated names together; sharing one says nothing about delegation.
GENERIC = frozenset(
    ["get", "set", "run", "make", "create", "new", "init", "build", "handle", "process", "exec", "execute", "call", "apply", "to", "from", "with", "is", "has", "do", "of", "the", "for", "self"]
)


@dataclass(frozen=True)
class Delegation:
    """`target` holds the behaviour that `wrappers` (outermost first) only pass along to."""

    target: SymbolRow
    wrappers: tuple[str, ...]


def is_thin(symbol: SymbolRow) -> bool:
    """A function or method whose whole definition is a few lines (a class is never thin)."""
    return symbol.kind in ("function", "method") and symbol.end - symbol.start + 1 <= THIN_SPAN


def _parts(name: str) -> set[str]:
    """Word parts of an identifier (`MinLengthCheck` -> min, length, check), without glue words
    or the joined compound the tokenizer also emits."""
    compound = name.lower().replace("_", "")
    parts = {tok for tok in tokenize(name) if tok != compound and "_" not in tok}
    return (parts or {compound}) - GENERIC


def related(wrapper: SymbolRow, target: SymbolRow) -> bool:
    """A facade is named after what it delegates to; a utility it merely uses is not."""
    return bool(_parts(wrapper.name) & _parts(target.name))


def follow(store: IndexStore, roots: list[SymbolRow]) -> list[Delegation]:
    """First non-wrapper symbol reached from each thin root, in root order, without duplicates."""
    found: list[Delegation] = []
    seen_targets: set[str] = set()
    for root in roots:
        if not is_thin(root):
            continue
        visited = {root.id}
        queue: deque[tuple[SymbolRow, tuple[SymbolRow, ...]]] = deque([(root, (root,))])
        while queue:
            current, path = queue.popleft()
            links = [
                link
                for link in store.callees(current.id)
                if link.confidence in TRUSTED
                and link.symbol.kind in CODE
                and link.symbol.id not in visited
                and not store._is_test(link.symbol.file)
            ]
            links.sort(key=lambda link: (link.confidence != "high", link.line or 0, link.symbol.id))
            for link in links[:MAX_FANOUT]:
                callee = link.symbol
                visited.add(callee.id)
                if is_thin(callee):
                    if len(path) < MAX_DEPTH:
                        queue.append((callee, (*path, callee)))
                    continue
                if callee.id not in seen_targets and any(related(w, callee) for w in path):
                    seen_targets.add(callee.id)
                    found.append(Delegation(callee, tuple(w.id for w in path)))
                if len(found) >= MAX_TARGETS:
                    return found
    return found
