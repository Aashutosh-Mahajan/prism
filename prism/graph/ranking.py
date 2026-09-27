"""Deterministic PageRank (power iteration) used for both graphs."""

from __future__ import annotations

from collections.abc import Callable, Iterable

DAMPING = 0.85
MAX_ITER = 100
TOLERANCE = 1e-10
PRECISION = 6

Ranker = Callable[[Iterable[str], Iterable[tuple[str, str]]], dict[str, float]]


def pagerank(nodes: Iterable[str], edges: Iterable[tuple[str, str]]) -> dict[str, float]:
    """PageRank over a directed graph. Rank flows from source to target.

    Duplicate edges add weight. Dangling nodes spread their rank uniformly.
    Results are rounded so the output is byte-stable across platforms.
    """
    order = sorted(set(nodes))
    n = len(order)
    if n == 0:
        return {}
    index = {node: i for i, node in enumerate(order)}
    out_weight = [0.0] * n
    incoming: list[dict[int, float]] = [{} for _ in range(n)]
    for src, dst in edges:
        if src == dst or src not in index or dst not in index:
            continue
        s, d = index[src], index[dst]
        out_weight[s] += 1.0
        incoming[d][s] = incoming[d].get(s, 0.0) + 1.0

    # Pre-normalized, sorted in-links: fixed summation order keeps results reproducible.
    links = [sorted((s, w / out_weight[s]) for s, w in inc.items()) for inc in incoming]
    dangling_nodes = [i for i in range(n) if out_weight[i] == 0.0]
    rank = [1.0 / n] * n
    base = (1.0 - DAMPING) / n
    for _ in range(MAX_ITER):
        spread = DAMPING * sum(rank[i] for i in dangling_nodes) / n
        new = [base + spread + DAMPING * sum(rank[s] * w for s, w in lk) for lk in links]
        delta = sum(abs(a - b) for a, b in zip(new, rank, strict=True))
        rank = new
        if delta < TOLERANCE:
            break
    return {node: round(rank[i], PRECISION) for i, node in enumerate(order)}


class LazyRanker:
    """Reuse previous scores when the edge set barely changed (CLAUDE.md 6.2).

    Full PageRank runs only when more than `max(min_changes, fraction * edges)`
    edges were added or removed. Otherwise existing nodes keep their previous
    score and new nodes get the smallest previous score; `approx` is set so
    the manifest can say the ranking is approximate until the next full scan.
    """

    def __init__(
        self,
        previous_ranks: dict[str, float],
        previous_edges: set[tuple[str, str]],
        min_changes: int = 10,
        fraction: float = 0.02,
    ) -> None:
        self.previous_ranks = previous_ranks
        self.previous_edges = previous_edges
        self.min_changes = min_changes
        self.fraction = fraction
        self.approx = False
        self.ran_full = False

    def __call__(self, nodes: Iterable[str], edges: Iterable[tuple[str, str]]) -> dict[str, float]:
        node_list = list(nodes)
        edge_set = set(edges)
        changed = len(edge_set ^ self.previous_edges)
        limit = max(self.min_changes, int(self.fraction * len(self.previous_edges)))
        if not self.previous_ranks or changed > limit:
            self.ran_full = True
            return pagerank(node_list, edge_set)
        if changed or set(node_list) != set(self.previous_ranks):
            self.approx = True
        floor = min(self.previous_ranks.values())
        return {n: self.previous_ranks.get(n, floor) for n in sorted(node_list)}
