"""Reverse-dependency traversal shared by `impact`, context packs, and `blast_radius.json`."""

from __future__ import annotations

from collections.abc import Iterable, Mapping


def reverse_bfs(
    seeds: Iterable[str],
    reverse: Mapping[str, Iterable[str]],
    max_depth: int = 3,
    cap: int = 500,
) -> dict[str, int]:
    """Nodes that (transitively) depend on `seeds`, mapped to their distance (1..max_depth).

    `reverse[x]` lists the nodes that depend on `x` (callers / importers).
    Traversal is breadth-first in sorted order so truncation at `cap` is deterministic.
    """
    seen = set(seeds)
    frontier = sorted(seen)
    out: dict[str, int] = {}
    for depth in range(1, max_depth + 1):
        nxt: list[str] = []
        for node in frontier:
            for dep in sorted(reverse.get(node, ())):
                if dep in seen:
                    continue
                seen.add(dep)
                out[dep] = depth
                nxt.append(dep)
                if len(out) >= cap:
                    return out
        if not nxt:
            break
        frontier = nxt
    return out
