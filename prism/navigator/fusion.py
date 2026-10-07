"""Independent reciprocal-rank fusion of body and symbol retrieval evidence.

Scores from source BM25 and symbol metadata are not numerically comparable;
ranks are. A file gets one vote per channel regardless of its symbol count.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

RRF_K = 60


def fuse_files(rankings: Sequence[Iterable[str]], limit: int) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        seen: set[str] = set()
        rank = 0
        for file in ranking:
            if file in seen:
                continue
            seen.add(file)
            rank += 1
            scores[file] = scores.get(file, 0.0) + 1.0 / (RRF_K + rank)
    best = max(scores.values(), default=1.0)
    return [
        (file, score / best)
        for file, score in sorted(scores.items(), key=lambda p: (-p[1], p[0]))[:limit]
    ]
