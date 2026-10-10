"""Seed selection and a bounded walk over the call graph, for explanation requests."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping, Sequence


def pick_seeds(
    scored: Sequence[tuple[float, str]],
    labels: Mapping[str, str],
    best_by_term: Mapping[str, str],
    *,
    max_k: int = 3,
    max_total: int = 6,
    gap_ratio: float = 0.2,
) -> list[str]:
    """Choose starting nodes: the strongest matches, then one winner per request term.

    Nodes sharing a label count once, so a name defined in several places does not
    take every slot. Strong matches stop where the score falls below `gap_ratio` of
    the best one.
    """
    positive = sorted(((s, n) for s, n in scored if s > 0), key=lambda p: (-p[0], p[1]))
    if not positive or max_k <= 0 or max_total <= 0:
        return []
    allowed = {node for _, node in positive}
    floor = positive[0][0] * gap_ratio
    chosen: list[str] = []
    labels_taken: set[str] = set()

    def take(node: str) -> None:
        label = labels.get(node, node).casefold() or node
        if node in allowed and label not in labels_taken and len(chosen) < max_total:
            labels_taken.add(label)
            chosen.append(node)

    for score, node in positive:
        if len(chosen) >= min(max_k, max_total) or score < floor:
            break
        take(node)
    for term in sorted(best_by_term):
        take(best_by_term[term])
    return chosen


def walk_graph(
    seeds: Sequence[str],
    neighbors: Callable[[str], Sequence[str]],
    *,
    depth: int = 2,
    max_nodes: int = 40,
    max_neighbors: int = 12,
    hub_threshold: int = 50,
) -> list[tuple[str, int, str | None]]:
    """Breadth-first walk returning (node, distance, parent), seeds first.

    `neighbors` is expected to list the most relevant nodes first. A node outside the
    seeds with `hub_threshold` or more neighbours is not expanded, and the node and
    fan-out caps bound the work without measuring the whole graph.
    """
    order: list[tuple[str, int, str | None]] = []
    seen: set[str] = set()
    queue: deque[tuple[str, int]] = deque()
    seed_set = set(seeds)
    for seed in seeds:
        if seed not in seen and len(order) < max_nodes:
            seen.add(seed)
            order.append((seed, 0, None))
            queue.append((seed, 0))
    while queue:
        node, distance = queue.popleft()
        if distance >= depth:
            continue
        adjacent = neighbors(node)
        if node not in seed_set and len(adjacent) >= hub_threshold:
            continue
        for other in adjacent[:max_neighbors]:
            if other in seen:
                continue
            if len(order) >= max_nodes:
                return order
            seen.add(other)
            order.append((other, distance + 1, node))
            queue.append((other, distance + 1))
    return order
