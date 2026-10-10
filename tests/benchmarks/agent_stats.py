"""Offline analysis of frozen agent-session JSONL; no agent or provider calls.

    python -m tests.benchmarks.agent_stats results.jsonl --output report.json

One row per scored session: arm, task, rep, success, input_tokens,
cache_read_tokens, output_tokens; optional repo. Input excludes cache reads.
All arms must contain the same task/repetition cells, including failed sessions.
Files must describe one host/model/configuration. Infrastructure retries must
first be consolidated with their tokens retained under the scoring protocol.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

Cell = tuple[str, str, int]
Task = tuple[str, str]
METRICS = ("fresh_input", "processed_input", "total_tokens")


def _metric(row: dict[str, Any], metric: str) -> float:
    value = float(row["input_tokens"])
    if metric != "fresh_input":
        value += row["cache_read_tokens"]
    if metric == "total_tokens":
        value += row["output_tokens"]
    return value


def validate(rows: list[dict[str, Any]]) -> dict[str, dict[Cell, dict[str, Any]]]:
    arms: dict[str, dict[Cell, dict[str, Any]]] = defaultdict(dict)
    identities = {tuple(str(row.get(key, "")) for key in ("agent", "model")) for row in rows}
    if len(identities) > 1:
        raise ValueError("Analyze each host/model separately")
    for row in rows:
        if not isinstance(row.get("success"), bool):
            raise ValueError("Every session needs an explicit boolean success, including failures")
        if not isinstance(row.get("rep"), int) or isinstance(row["rep"], bool) or row["rep"] < 1:
            raise ValueError("rep must be a positive integer")
        for key in ("input_tokens", "cache_read_tokens", "output_tokens"):
            value = row.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"Missing or invalid {key}; unknown usage is not zero")
        arm, task = row.get("arm"), row.get("task")
        if not isinstance(arm, str) or not arm or not isinstance(task, str) or not task:
            raise ValueError("Every row needs arm and task names")
        cell = (str(row.get("repo", "")), task, row["rep"])
        if cell in arms[arm]:
            raise ValueError(f"Duplicate session cell: {arm} {cell}")
        arms[arm][cell] = row
    if not arms.get("baseline"):
        raise ValueError("A baseline is required")
    expected = set(arms["baseline"])
    repetitions: dict[Task, set[int]] = defaultdict(set)
    for repo, task, rep in expected:
        repetitions[(repo, task)].add(rep)
    reference = next(iter(repetitions.values()))
    if reference != set(range(1, max(reference) + 1)) or any(
        reps != reference for reps in repetitions.values()
    ):
        raise ValueError("Incomplete repetition schedule; include every attempted session")
    for arm, cells in arms.items():
        if set(cells) != expected:
            raise ValueError(
                f"Unmatched task/repetition cells in {arm}; do not silently drop failures"
            )
    return dict(arms)


def analyze(rows: list[dict[str, Any]], *, draws: int = 4000, seed: int = 7) -> dict[str, Any]:
    if draws < 100:
        raise ValueError("At least 100 bootstrap draws are required")
    arms = validate(rows)
    base = arms["baseline"]
    tasks: dict[Task, list[Cell]] = defaultdict(list)
    for cell in sorted(base):
        tasks[cell[:2]].append(cell)
    task_names = sorted(tasks)
    out: dict[str, Any] = {
        "seed": seed,
        "bootstrap_draws": draws,
        "interval_level": 0.95,
        "estimand": "paired ratio of mean session tokens; equal task weights",
        "resampling": "tasks, then matched repetition pairs within sampled tasks",
        "repetitions": len(next(iter(tasks.values()))),
        "tasks": len(tasks),
        "arms": {},
    }
    for arm, cells in sorted(arms.items()):
        sessions = list(cells.values())
        solved = sum(row["success"] for row in sessions)
        result: dict[str, Any] = {
            "sessions": len(sessions),
            "solved": solved,
            "pass_rate": solved / len(sessions),
            "pass_power_k": sum(all(cells[c]["success"] for c in group) for group in tasks.values())
            / len(tasks),
            "tokens_per_solved_task": sum(_metric(r, "total_tokens") for r in sessions) / solved
            if solved
            else None,
            "metrics": {},
        }
        for metric in METRICS:
            denominator = sum(_metric(row, metric) for row in base.values())
            if denominator <= 0:
                raise ValueError(f"Baseline {metric} is zero; relative savings are undefined")
            point = (sum(_metric(row, metric) for row in sessions) / denominator - 1) * 100
            rng = random.Random(seed)  # same draws across arms and metrics
            samples: list[float] = []
            for _ in range(draws):
                sampled: list[Cell] = []
                for _ in task_names:
                    group = tasks[rng.choice(task_names)]
                    sampled.extend(rng.choice(group) for _ in group)
                b = sum(_metric(base[c], metric) for c in sampled)
                if b <= 0:
                    raise ValueError(f"Zero baseline in bootstrap for {metric}")
                samples.append((sum(_metric(cells[c], metric) for c in sampled) / b - 1) * 100)
            samples.sort()
            result["metrics"][metric] = {
                "mean": sum(_metric(row, metric) for row in sessions) / len(sessions),
                "change_percent": point,
                "interval_percent": [samples[int(draws * 0.025)], samples[int(draws * 0.975) - 1]],
            }
        if all(isinstance(row.get("hook_delivered"), bool) for row in sessions):
            result["hook_delivery_rate"] = sum(row["hook_delivered"] for row in sessions) / len(
                sessions
            )
        out["arms"][arm] = result
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--draws", type=int, default=4000)
    args = parser.parse_args()
    rows = [
        json.loads(line)
        for line in args.file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    try:
        result = analyze(rows, draws=args.draws, seed=args.seed)
    except ValueError as exc:
        parser.error(str(exc))
    text = json.dumps(result, indent=2, allow_nan=False)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
