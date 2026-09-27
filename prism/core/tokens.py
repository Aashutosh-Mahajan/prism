"""Token estimation used for every budget in PRISM.

Documented approximation: one token per four characters, rounded up. It is
deterministic and dependency-free; budgets are sized with it in mind.
"""

from __future__ import annotations


def estimate_tokens(text: str) -> int:
    return (len(text) + 3) // 4
