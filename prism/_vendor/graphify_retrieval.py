# Copyright 2026 Safi Shamsi and the Graphify contributors.
# SPDX-License-Identifier: Apache-2.0
# Adapted from Graphify graphify/serve.py at
# f765dcb3415d60fcfce390868da49e77894f2dc2 (_pick_seeds and _bfs).
# Changes: dependency-free interfaces, deterministic ordering, hard work caps,
# and query relevance ordering instead of unbounded neighborhood expansion.
# See licenses/graphify/ for the upstream license and NOTICE.
"""Diverse graph seeds and bounded, hub-aware traversal adapted for PRISM."""

from __future__ import annotations

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
    """Keep dominant matches, then give other request terms a bounded seed slot.

    Homonymous labels share a slot. Per-term winners are supplied by the caller
    so this does not require one whole-graph scoring pass per query word.
    """
    if not scored or max_k <= 0 or max_total <= 0:
        return []
    ranked = sorted(scored, key=lambda pair: (-pair[0], pair[1]))
    eligible = {node for score, node in ranked if score > 0}
    top_score = ranked[0][0]
    seeds: list[str] = []
    seen_labels: set[str] = set()

    def add(node: str) -> None:
        key = labels.get(node, node).casefold() or node
        if node in eligible and key not in seen_labels and len(seeds) < max_total:
            seen_labels.add(key)
            seeds.append(node)

    for score, node in ranked:
        if len(seeds) >= min(max_k, max_total):
            break
        if score <= 0 or (seeds and score < top_score * gap_ratio):
            break
        add(node)
    for term in sorted(best_by_term):
        add(best_by_term[term])
    return seeds


def walk_graph(
    seeds: Sequence[str],
    neighbors: Callable[[str], Sequence[str]],
    *,
    depth: int = 2,
    max_nodes: int = 40,
    max_neighbors: int = 12,
    hub_threshold: int = 50,
) -> list[tuple[str, int, str | None]]:
    """Return (node, distance, parent), with seeds first and no hub fan-out.

    The caller orders neighbors by evidence/confidence. A fixed threshold and
    caps avoid scanning the whole graph to compute a degree percentile.
    """
    visited: set[str] = set()
    found: list[tuple[str, int, str | None]] = []
    frontier: list[str] = []
    for node in seeds:
        if node not in visited and len(found) < max_nodes:
            visited.add(node)
            found.append((node, 0, None))
            frontier.append(node)
    seed_set = set(frontier)
    for distance in range(1, depth + 1):
        next_frontier: list[str] = []
        for node in frontier:
            adjacent = neighbors(node)
            if node not in seed_set and len(adjacent) >= hub_threshold:
                continue
            for other in adjacent[:max_neighbors]:
                if other in visited:
                    continue
                if len(found) >= max_nodes:
                    return found
                visited.add(other)
                found.append((other, distance, node))
                next_frontier.append(other)
        frontier = next_frontier
        if not frontier:
            break
    return found
