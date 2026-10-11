"""Offline context precision/recall: python -m tests.benchmarks.context_score REPLAY.

Consumes frozen T00 replay packets; no model calls and no repository reindexing.
File gold includes new files. Block/line gold uses scorable parent-side hunks.
Optional transcript-derived used_lines is explicit evidence, not inferred thinking.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from tests.benchmarks.replay_precision import parse_hunks, parse_packet


def measures(found: int, delivered: int, expected: int) -> dict[str, float | int]:
    precision = found / delivered if delivered else 0.0
    recall = found / expected if expected else 0.0
    return {
        "found": found,
        "delivered": delivered,
        "expected": expected,
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
    }


def score_context(
    text: str,
    gold_files: list[str],
    gold_blocks: list[tuple[str, int, int]],
    used_lines: list[tuple[str, int, int]] | None = None,
) -> dict[str, Any]:
    blocks = parse_packet(text)
    predicted_files = {block.file for block in blocks}
    gold = set(gold_files)
    relevant = [span for span in gold_blocks if span[0] in gold]
    predicted_lines = {(block.file, line) for block in blocks for line in block.delivered_lines}
    wanted = {(file, line) for file, start, end in relevant for line in range(start, end + 1)}
    hit_blocks = sum(
        bool({(block.file, line) for line in block.delivered_lines} & wanted) for block in blocks
    )
    found_blocks = sum(
        bool({(file, line) for line in range(start, end + 1)} & predicted_lines)
        for file, start, end in relevant
    )
    # Block precision and recall have different numerators: any-overlap matching
    # allows one delivered body to cover several disjoint gold hunks.
    block_score = measures(hit_blocks, len(blocks), len(relevant))
    block_score["found_gold"] = found_blocks
    block_score["recall"] = found_blocks / len(relevant) if relevant else 0.0
    precision, recall = float(block_score["precision"]), float(block_score["recall"])
    block_score["f1"] = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    used = None
    if used_lines is not None:
        observed = {
            (file, line) for file, start, end in used_lines for line in range(start, end + 1)
        }
        used = len(predicted_lines & observed) / len(predicted_lines) if predicted_lines else 0.0
    return {
        "file": measures(len(predicted_files & gold), len(predicted_files), len(gold)),
        "block": block_score,
        "line": measures(len(predicted_lines & wanted), len(predicted_lines), len(wanted)),
        "context_used_share": used,
        "usage_evidence": "explicit transcript ranges" if used_lines is not None else "unavailable",
        "packet_characters": len(text),
    }


def score_replay(report: dict[str, Any]) -> dict[str, Any]:
    cases = []
    for row in report["rows"]:
        text = row.get("packet", row.get("text", ""))
        if not text:
            raise ValueError("replay must preserve raw packet text")
        hunks = row.get("hunks")
        if hunks is None:
            hunks = parse_hunks(row.get("diff", ""))
        cases.append(
            {
                "sha": row["sha"],
                "query": row["query"],
                **score_context(
                    text, row["gold"], [tuple(span) for span in hunks], row.get("used_lines")
                ),
                "packet_tokens": row.get("packet_tokens"),
                "cost": row.get("cost"),
            }
        )
    summary = {}
    for level in ("file", "block", "line"):
        found = sum(case[level]["found"] for case in cases)
        delivered = sum(case[level]["delivered"] for case in cases)
        expected = sum(case[level]["expected"] for case in cases)
        summary[level] = measures(found, delivered, expected)
        if level == "block":
            recall = (
                sum(case[level]["found_gold"] for case in cases) / expected if expected else 0.0
            )
            precision = float(summary[level]["precision"])
            summary[level].update(
                recall=recall,
                f1=2 * precision * recall / (precision + recall) if precision + recall else 0.0,
            )
    provenance = report.get("provenance") or {
        key: value for key, value in report.items() if key not in {"rows", "summary"}
    }
    return {
        "provenance": provenance,
        "definitions": "file: exact; block: any overlap; line: exact union; parent-side scorable hunks",
        "summary": summary,
        "cases": cases,
    }


def check_regression(
    current: dict[str, Any], baseline: dict[str, Any], recall_margin: float = 0.02
) -> None:
    if current["summary"]["file"]["recall"] + recall_margin < baseline["summary"]["file"]["recall"]:
        raise AssertionError("file recall regressed beyond the owner's two-point margin")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("replay", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    result = score_replay(json.loads(args.replay.read_text(encoding="utf-8")))
    if args.baseline:
        check_regression(result, json.loads(args.baseline.read_text(encoding="utf-8")))
    target = (
        args.output
        or Path("output/benchmarks")
        / f"context-score-{result['provenance']['engine_head'][:12]}.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("Level       Precision   Recall      F1")
    for level, score in result["summary"].items():
        print(f"{level:10}  {score['precision']:9.2%}  {score['recall']:7.2%}  {score['f1']:7.2%}")
    print(f"Saved {target}")


if __name__ == "__main__":
    main()
