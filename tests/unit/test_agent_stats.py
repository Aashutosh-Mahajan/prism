from copy import deepcopy

import pytest

from tests.benchmarks.agent_stats import analyze


def rows() -> list[dict]:
    return [
        {
            "arm": arm,
            "task": task,
            "rep": rep,
            "success": True,
            "input_tokens": 100 if arm == "baseline" else value,
            "cache_read_tokens": 0,
            "output_tokens": 10,
        }
        for task, value in (("a", 10), ("b", 190))
        for rep in (1, 2, 3)
        for arm in ("baseline", "cli")
    ]


def test_bootstrap_resamples_tasks_not_just_repetitions() -> None:
    result = analyze(rows(), draws=200)
    metric = result["arms"]["cli"]["metrics"]["processed_input"]
    assert metric["change_percent"] == 0
    assert metric["interval_percent"] == pytest.approx([-90, 90])
    assert result == analyze(rows(), draws=200)


def test_failures_keep_tokens_and_reduce_pass_power_k() -> None:
    data = rows()
    next(row for row in data if row["arm"] == "cli")["success"] = False
    result = analyze(data, draws=100)["arms"]["cli"]
    assert result["tokens_per_solved_task"] == 660 / 5
    assert result["pass_power_k"] == 0.5


@pytest.mark.parametrize("change", ["missing", "duplicate", "unknown_usage", "string_success"])
def test_invalid_or_unpaired_records_are_rejected(change: str) -> None:
    data = deepcopy(rows())
    if change == "missing":
        data.pop()
    elif change == "duplicate":
        data.append(data[0])
    elif change == "unknown_usage":
        del data[0]["output_tokens"]
    else:
        data[0]["success"] = "false"
    with pytest.raises(ValueError):
        analyze(data, draws=100)


def test_no_solved_tasks_is_null_and_unknown_delivery_is_not_zero() -> None:
    data = rows()
    for row in data:
        if row["arm"] == "cli":
            row["success"] = False
    result = analyze(data, draws=100)["arms"]["cli"]
    assert result["tokens_per_solved_task"] is None
    assert "hook_delivery_rate" not in result
