"""Deterministic Louvain community detection over the module graph.

Communities group modules that depend on each other more than on the rest of
the codebase. They are stored in `dependency_graph.json` (`community` per
module) and used for the viewer's cluster colouring, so the index and the
picture agree. Deterministic: nodes are visited in sorted order and ties
break on the smallest community id.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

MAX_PASSES = 10
MIN_GAIN = 1e-9


def _one_level(
    nodes: list[str], adj: dict[str, dict[str, float]], total: float
) -> tuple[dict[str, str], bool]:
    comm = {n: n for n in nodes}
    degree = {n: sum(adj[n].values()) for n in nodes}
    comm_tot = dict(degree)
    improved = False
    for _ in range(MAX_PASSES):
        moved = False
        for n in nodes:
            current = comm[n]
            weights: dict[str, float] = defaultdict(float)
            for m, w in adj[n].items():
                if m != n:
                    weights[comm[m]] += w
            comm_tot[current] -= degree[n]
            best, best_gain = (
                current,
                weights.get(current, 0.0) - comm_tot[current] * degree[n] / (2 * total),
            )
            for c in sorted(weights):
                gain = weights[c] - comm_tot[c] * degree[n] / (2 * total)
                if gain > best_gain + MIN_GAIN:
                    best, best_gain = c, gain
            comm_tot[best] += degree[n]
            if best != current:
                comm[n] = best
                moved = improved = True
        if not moved:
            break
    return comm, improved


def louvain(nodes: Iterable[str], edges: Iterable[tuple[str, str, float]]) -> dict[str, int]:
    """Community index per node (0 = largest community). Edges are treated as undirected."""
    node_list = sorted(set(nodes))
    adj: dict[str, dict[str, float]] = {n: {} for n in node_list}
    for a, b, w in edges:
        if a == b or a not in adj or b not in adj:
            continue
        adj[a][b] = adj[a].get(b, 0.0) + w
        adj[b][a] = adj[b].get(a, 0.0) + w
    total = sum(sum(v.values()) for v in adj.values()) / 2
    membership = {n: n for n in node_list}
    if total == 0:
        return {n: i for i, n in enumerate(node_list)}
    level_nodes, level_adj = node_list, adj
    while True:
        comm, improved = _one_level(level_nodes, level_adj, total)
        if not improved:
            break
        membership = {n: comm[membership[n]] for n in node_list}
        # Collapse communities into super-nodes and repeat.
        new_adj: dict[str, dict[str, float]] = {c: {} for c in sorted(set(comm.values()))}
        for a, nbrs in level_adj.items():
            for b, w in nbrs.items():
                ca, cb = comm[a], comm[b]
                new_adj[ca][cb] = new_adj[ca].get(cb, 0.0) + w
        level_nodes, level_adj = sorted(new_adj), new_adj
    groups: dict[str, list[str]] = defaultdict(list)
    for n, c in membership.items():
        groups[c].append(n)
    ordered = sorted(groups.values(), key=lambda members: (-len(members), min(members)))
    return {n: i for i, members in enumerate(ordered) for n in members}
