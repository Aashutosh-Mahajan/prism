"""Paired log comparisons with task-cluster bootstrap and baseline covariates."""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path


def cost_proxy(row):
    # Frozen Sonnet-priced comparison units, never GPT pricing or a subscription bill.
    return row["input_tokens"] + 0.1 * row["cache_read_tokens"] + 5 * row["output_tokens"]


def pairs(rows, arm, reference="baseline"):
    cells = defaultdict(dict)
    for row in rows:
        if row["arm"] not in (reference, arm):
            continue
        key = (row["repo"], row["task"], row["rep"])
        if row["arm"] in cells[key]:
            raise ValueError("duplicate trial")
        if not row.get("usage_known"):
            raise ValueError("unknown usage remains unknown; analysis unavailable")
        for metric in ("input_tokens", "cache_read_tokens", "output_tokens"):
            if not isinstance(row.get(metric), int) or row[metric] < 0:
                raise ValueError("invalid token class")
        cells[key][row["arm"]] = row
    if not cells or any(set(value) != {reference, arm} for value in cells.values()):
        raise ValueError("unmatched paired cells")
    return [(value[reference], value[arm]) for _, value in sorted(cells.items())]


def summarize(data, draws=4000, seed=20261011):
    grouped = defaultdict(list)
    for baseline, treatment in data:
        grouped[(baseline["repo"], baseline["task"])].append((baseline, treatment))
    log_base = [math.log(cost_proxy(b)) for b, _ in data]
    differences = [math.log(cost_proxy(t) / cost_proxy(b)) for b, t in data]
    strata = defaultdict(list)
    for index, (baseline, _) in enumerate(data):
        strata[(baseline["repo"], baseline["kind"])].append(index)
    residual_base = [0.0] * len(data)
    residual_difference = [0.0] * len(data)
    for indices in strata.values():
        xbar = statistics.mean(log_base[i] for i in indices)
        ybar = statistics.mean(differences[i] for i in indices)
        for i in indices:
            residual_base[i] = log_base[i] - xbar
            residual_difference[i] = differences[i] - ybar
    variance = sum(x * x for x in residual_base)
    slope = (
        sum(x * y for x, y in zip(residual_base, residual_difference, strict=True)) / variance
        if variance
        else 0.0
    )
    adjusted = [d - slope * x for d, x in zip(differences, residual_base, strict=True)]
    by_identity = {(b["repo"], b["task"], b["rep"]): i for i, (b, _) in enumerate(data)}
    rng = random.Random(seed)
    samples, adjusted_samples, correctness = [], [], []
    repeated_samples = []
    repeated_known = all(
        isinstance(row.get("repeated_file_edit_events"), int) for pair in data for row in pair
    )
    names = sorted(grouped)
    for _ in range(draws):
        selected = []
        for _ in names:
            group = grouped[rng.choice(names)]
            selected.extend(rng.choice(group) for _ in group)
        indices = [by_identity[(b["repo"], b["task"], b["rep"])] for b, _ in selected]
        samples.append(math.exp(statistics.mean(differences[i] for i in indices)))
        adjusted_samples.append(math.exp(statistics.mean(adjusted[i] for i in indices)))
        correctness.append(
            statistics.mean(int(t["success"]) - int(b["success"]) for b, t in selected)
        )

        if repeated_known:
            repeated_samples.append(
                statistics.mean(
                    t["repeated_file_edit_events"] - b["repeated_file_edit_events"]
                    for b, t in selected
                )
            )

    def interval(values):
        values = sorted(values)
        return [values[int(draws * 0.025)], values[min(draws - 1, int(draws * 0.975))]]

    result = {
        "pairs": len(data),
        "tasks": len(grouped),
        "draws": draws,
        "cost_proxy": "uncached + 0.1*cached + 5*output; Sonnet comparison units, not a bill",
        "geometric_cost_ratio": math.exp(statistics.mean(differences)),
        "geometric_ratio_ci95": interval(samples),
        "aggregate_cost_ratio": sum(cost_proxy(t) for _, t in data)
        / sum(cost_proxy(b) for b, _ in data),
        "baseline_covariate_adjusted_ratio": math.exp(statistics.mean(adjusted)),
        "baseline_covariate_adjusted_ci95": interval(adjusted_samples),
        "baseline_log_slope": slope,
        "covariates": "baseline log usage centered within repository/task-type strata; fixed fitted slope in bootstrap",
        "correctness_difference": statistics.mean(
            int(t["success"]) - int(b["success"]) for b, t in data
        ),
        "correctness_difference_ci95": interval(correctness),
        "repeated_file_edit_difference_ci95": interval(repeated_samples)
        if repeated_known
        else None,
        "pass_at_1": sum(t["success"] for _, t in data) / len(data),
        "pass_power_k": sum(all(t["success"] for _, t in group) for group in grouped.values())
        / len(grouped),
        "api_spend": sum(t["api_spend"] for _, t in data),
        "comparison_proxy_dollars": sum(cost_proxy(t) for _, t in data) * 2 / 1_000_000,
        "tokens_per_solved_task": sum(
            t["input_tokens"] + t["cache_read_tokens"] + t["output_tokens"] for _, t in data
        )
        / sum(t["success"] for _, t in data)
        if any(t["success"] for _, t in data)
        else None,
        "token_classes": {
            key: sum(t[key] for _, t in data)
            if all(isinstance(t.get(key), int) for _, t in data)
            else None
            for key in (
                "input_tokens",
                "cache_read_tokens",
                "cache_write_input_tokens",
                "output_tokens",
                "thinking_tokens",
            )
        },
        "model_turns": sum(t["model_turns"] for _, t in data)
        if all(isinstance(t.get("model_turns"), int) for _, t in data)
        else None,
    }
    for label, key in (("repository", "repo"), ("task_type", "kind")):
        result[label] = {}
        for value in sorted({b[key] for b, _ in data}):
            subset = [(b, t) for b, t in data if b[key] == value]
            result[label][value] = {
                "pairs": len(subset),
                "pass_at_1": sum(t["success"] for _, t in subset) / len(subset),
                "geometric_cost_ratio": math.exp(
                    statistics.mean(math.log(cost_proxy(t) / cost_proxy(b)) for b, t in subset)
                ),
            }
    return result


def analyze(rows, pilot=False, draws=4000):
    output = {"arms": {}, "raw_cells": len(rows), "unknown_usage_is_zero": False}
    for arm in sorted({row["arm"] for row in rows} - {"baseline", "hint"}):
        data = pairs(rows, arm)
        output["arms"][arm] = summarize(data, draws)
    if any(row["arm"] == "hint" for row in rows):
        keys = {(r["repo"], r["task"], r["rep"]) for r in rows if r["arm"] == "hint"}
        study = [
            r
            for r in rows
            if r["arm"] in {"hook", "hint"} and (r["repo"], r["task"], r["rep"]) in keys
        ]
        comparison = summarize(pairs(study, "hint", "hook"), draws)
        repeated = comparison["repeated_file_edit_difference_ci95"]
        benefit = comparison["correctness_difference_ci95"][0] > 0 or (
            repeated is not None and repeated[1] < 0
        )
        output["post_edit_hint_study"] = comparison
        output["keep_post_edit_hint"] = benefit and comparison["geometric_ratio_ci95"][1] <= 1
    if pilot:
        data = pairs(rows, "hook")
        if len(data) != 20 or len({(b["repo"], b["task"]) for b, _ in data}) != 10:
            raise ValueError("pilot requires 10 tasks x 2 repetitions x 2 arms")
        logs = [math.log(cost_proxy(t) / cost_proxy(b)) for b, t in data]
        processed = [
            math.log(
                (t["input_tokens"] + t["cache_read_tokens"])
                / (b["input_tokens"] + b["cache_read_tokens"])
            )
            for b, t in data
        ]
        sd = max(statistics.stdev(logs), statistics.stdev(processed))
        count = max(80, math.ceil((1.96 * sd / math.log(1.15)) ** 2))
        output["pilot"] = {
            "paired_log_sd": sd,
            "minimum_pairs": count,
            "confirmation_tasks": 30,
            "confirmation_repetitions": max(5, math.ceil(count / 30)),
        }
    if {"hook", "hook_mcp"} <= {row["arm"] for row in rows}:
        comparison = summarize(pairs(rows, "hook", "hook_mcp"), draws)
        output["hook_vs_combined"] = comparison
        output["hook_only_gate"] = (
            comparison["correctness_difference_ci95"][0] > -0.05
            and comparison["geometric_ratio_ci95"][1] <= 1
        )
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pilot", action="store_true")
    args = parser.parse_args()
    rows = [
        json.loads(line)
        for line in args.input.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    args.output.write_text(
        json.dumps(analyze(rows, args.pilot), indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
