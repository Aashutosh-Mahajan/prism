"""Frozen price-table arithmetic. No provider calls, subscription billing or inferred usage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PRICING = Path(__file__).with_name("pricing.json")


def usage_cost(row: dict[str, Any], pricing: dict[str, Any] | None = None) -> dict[str, Any]:
    table = pricing or json.loads(PRICING.read_text(encoding="utf-8"))
    name = str(row.get("model", "unknown"))
    rates = table["models"].get(name)
    fallback = rates is None
    rates = dict(table["fallback"] if fallback else rates)
    fresh = row.get("uncached_input_tokens", row["input_tokens"])
    read = row["cache_read_tokens"]
    write_1h = row.get("cache_write_1h_tokens", 0)
    write_5m = row.get("cache_write_5m_tokens", row.get("cache_creation_input_tokens", 0))
    output = row["output_tokens"]
    counts = {
        "uncached_input": fresh,
        "cache_write_5m": write_5m,
        "cache_write_1h": write_1h,
        "cache_read": read,
        "output": output,
    }
    if any(not isinstance(n, int) or isinstance(n, bool) or n < 0 for n in counts.values()):
        raise ValueError("Token-class counts must be nonnegative integers")
    prompt = row.get("max_prompt_tokens")
    long = prompt is not None and prompt > rates.get("long_threshold", float("inf"))
    input_rate = rates["long_input"] if long else rates["input"]
    output_rate = rates["long_output"] if long else rates["output"]
    dollars = {
        "uncached_input": fresh * input_rate / 1_000_000,
        "cache_write_5m": write_5m * input_rate * rates.get("cache_write_5m", 1.25) / 1_000_000,
        "cache_write_1h": write_1h * input_rate * rates.get("cache_write_1h", 2) / 1_000_000,
        "cache_read": read * input_rate * rates["cache_read"] / 1_000_000,
        "output": output * output_rate / 1_000_000,
    }
    fixed = (
        sum(dollars.values()) - dollars["cache_write_1h"] + write_1h * input_rate * 1.25 / 1_000_000
    )
    return {
        "model": name,
        "pricing_fallback": fallback,
        "pricing_date": table["retrieved"],
        "token_classes": counts,
        "new_context_tokens": fresh + write_5m + write_1h,
        "dollars_by_class": dollars,
        "dollars": sum(dollars.values()),
        "fixed_cache_dollars": fixed,
        "pricing_warning": table["fallback_note"] if fallback else None,
        "long_context": long,
        "long_context_unknown": "long_threshold" in rates and prompt is None,
    }
