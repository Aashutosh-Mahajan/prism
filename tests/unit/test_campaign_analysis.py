"""Paired evidence cannot silently drop failures or invent missing usage."""

import pytest

from tests.benchmarks.campaign_analysis import analyze, pairs


def rows():
    return [
        {
            "repo": "example",
            "task": f"task-{task}",
            "rep": rep,
            "arm": arm,
            "kind": "edit",
            "input_tokens": 1000 if arm == "baseline" else 500,
            "cache_read_tokens": 2000,
            "cache_write_input_tokens": 0,
            "output_tokens": 100,
            "thinking_tokens": 20,
            "model_turns": 3,
            "success": True,
            "usage_known": True,
            "api_spend": 0,
        }
        for task in range(3)
        for rep in (1, 2)
        for arm in ("baseline", "hook")
    ]


def test_paired_ratio_cost_classes_and_pass_power():
    result = analyze(rows(), draws=200)["arms"]["hook"]
    assert result["pairs"] == 6 and result["tasks"] == 3
    assert result["geometric_cost_ratio"] == pytest.approx(1200 / 1700)
    assert result["geometric_ratio_ci95"][1] < 1
    assert result["pass_at_1"] == result["pass_power_k"] == 1
    assert result["token_classes"]["input_tokens"] == 3000
    assert result["api_spend"] == 0


def test_unmatched_unknown_and_failed_cells():
    data = rows()
    with pytest.raises(ValueError, match="unmatched"):
        pairs(data[:-1], "hook")
    data[0]["usage_known"] = False
    with pytest.raises(ValueError, match="unknown usage"):
        pairs(data, "hook")
    data = rows()
    data[-1]["success"] = False
    result = analyze(data, draws=200)["arms"]["hook"]
    assert result["pass_at_1"] == pytest.approx(5 / 6)
    assert result["pass_power_k"] == pytest.approx(2 / 3)
    with pytest.raises(ValueError, match="pilot requires"):
        analyze(data, pilot=True, draws=200)
