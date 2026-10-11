"""Observed full-suite duration, or an explicit owner setting; never guess a duration."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path


def record_full_suite(root: Path, command: str, seconds: float) -> None:
    # Conservative: paths, node ids, -k/-m and other selectors are not full runs.
    if not re.fullmatch(r"(?:python(?:3)? -m )?pytest(?: (?:-q|-v|--quiet|--verbose))*", command):
        return
    if not math.isfinite(seconds) or seconds < 0:
        return
    from prism.consent import cache_root
    from prism.writers.json_writer import write_json

    write_json(cache_root(root) / "full-suite-timing.json", {"seconds": seconds})


def slow_suite_warning(root: Path) -> str | None:
    from prism.config import load_config
    from prism.consent import cache_root

    configured = load_config(root).extra.get("slow_tests") is True
    seconds = 0.0
    try:
        value = json.loads(
            (cache_root(root) / "full-suite-timing.json").read_text(encoding="utf-8")
        )["seconds"]
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            seconds = float(value)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    if seconds > 120:
        return f"full suite takes ~{seconds / 60:.0f} min; run the named tests only"
    if configured:
        return "full suite is marked slow; run the named tests only"
    return None
