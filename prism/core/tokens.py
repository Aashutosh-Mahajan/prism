"""Token estimation used for every budget in PRISM.

Documented approximation: one token per four characters, rounded up. It is
deterministic and dependency-free; budgets are sized with it in mind.
"""

from __future__ import annotations

import math


def estimate_tokens(text: str, scale: float = 1.0) -> int:
    if isinstance(scale, bool) or not math.isfinite(scale) or scale <= 0:
        raise ValueError("token scale must be positive and finite")
    return (len(text) + 3) // 4 if scale == 1.0 else math.ceil(len(text) * scale / 4)
