"""Local ranking feedback: files an agent edited rank slightly higher for later requests.

A deterministic table in `.aicontext/cache/ranking_feedback.json` (a disposable, gitignored
cache, not an index artifact): per file, an edit weight that halves every 30 days. It can reorder
close candidates by at most `MAX_BOOST` and never outranks an exact name match. Turn it off with
`ranking_feedback = false` in `[tool.prism]` or `PRISM_FEEDBACK=0`; ranking is then exactly the
unboosted one. Nothing leaves the machine. See docs/adr/0005-local-ranking-feedback.md.
"""

from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path

FILE = "ranking_feedback.json"
HALF_LIFE_DAYS = 30.0
MAX_BOOST = 0.25  # a candidate's score is multiplied by at most 1 + MAX_BOOST
STEP = 0.08
MAX_FILES = 500

_cache: dict[str, tuple[float, dict[str, float]]] = {}


def enabled(root: Path) -> bool:
    env = os.environ.get("PRISM_FEEDBACK")
    if env is not None:
        return env != "0"
    try:
        from prism.config import load_config

        return load_config(root).extra.get("ranking_feedback", True) is not False
    except Exception:
        return True


def _path(root: Path) -> Path:
    from prism.consent import cache_root

    return cache_root(root) / FILE


def _decay(age_seconds: float) -> float:
    return float(0.5 ** (max(age_seconds, 0.0) / (HALF_LIFE_DAYS * 86400)))


def _load(root: Path) -> dict[str, dict[str, float]]:
    try:
        data = json.loads(_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def record_edits(root: Path, files: list[str], now: float | None = None) -> None:
    """Count one edit for each repo-relative file. Never raises."""
    if not files or not enabled(root):
        return
    now = time.time() if now is None else now
    try:
        table = _load(root)
        for file in set(files):
            old = table.get(file) or {}
            weight = float(old.get("w", 0.0)) * _decay(now - float(old.get("t", now))) + 1.0
            table[file] = {"w": round(weight, 4), "t": round(now, 1)}
        if len(table) > MAX_FILES:
            newest = sorted(table, key=lambda f: -float(table[f].get("t", 0.0)))[:MAX_FILES]
            table = {f: table[f] for f in newest}
        path = _path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(table, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
    except (OSError, ValueError, TypeError):
        pass


def boosts(root: Path, now: float | None = None) -> dict[str, float]:
    """file -> multiplier fraction in (0, MAX_BOOST]; empty when disabled or nothing recorded."""
    if not enabled(root):
        return {}
    path = _path(root)
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return {}
    key = path.as_posix()
    hit = _cache.get(key)
    if hit is not None and hit[0] == stamp and now is None:
        return hit[1]
    now = time.time() if now is None else now
    out: dict[str, float] = {}
    for file, entry in _load(root).items():
        if not isinstance(entry, dict):
            continue
        weight = float(entry.get("w", 0.0)) * _decay(now - float(entry.get("t", now)))
        value = min(MAX_BOOST, STEP * math.log2(1.0 + weight))
        if value > 0.001:
            out[file] = value
    _cache[key] = (stamp, out)
    return out
