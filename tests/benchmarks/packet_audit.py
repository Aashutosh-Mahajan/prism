"""Packet composition audit: python -m tests.benchmarks.packet_audit.

Indexes a scratch HEAD worktree with the current engine. Character categories
are disjoint; line-number prefixes are separately reported as an overlay.
"""

from __future__ import annotations

import argparse
import json
import re
import tempfile
import time
from pathlib import Path
from typing import Any

from prism.core.tokens import estimate_tokens
from prism.navigator.api import op_task
from prism.navigator.task_pack import render_task
from tests.benchmarks.replay_precision import (
    HEADER,
    NUMBER,
    ROOT,
    historical_store,
    isolated_environment,
    provenance,
)

REQUESTS = Path(__file__).with_name("packet_audit_requests.json")


def is_test_file(file: str) -> bool:
    path = Path(file)
    return "tests" in path.parts or path.name.startswith("test_") or path.stem.endswith("_test")


def composition(text: str) -> dict[str, Any]:
    counts = dict.fromkeys(
        ("source_code", "test_code", "callers", "candidate_headers", "next_batch", "other"), 0
    )
    prefixes = test_callers = 0
    source = None
    fenced = callers = False
    for raw in text.splitlines(keepends=True):
        line = raw.rstrip("\r\n")
        if fenced:
            if line == "```":
                fenced = False
                category = "other"
            else:
                category = "test_code" if source and is_test_file(source) else "source_code"
                if match := NUMBER.match(line):
                    prefixes += match.end()
        elif match := HEADER.match(line):
            source = match[2]
            callers = False
            category = "candidate_headers"
        elif line == "```" and source:
            fenced = True
            category = "other"
        elif line.startswith("Callers of "):
            callers = True
            source = None
            category = "callers"
        elif callers and line.startswith("  "):
            category = "callers"
            if re.search(r"(?:^|\s)(?:[^\s]*/)?tests/|\btest_[^\s]*\.py", line):
                test_callers += len(raw)
        else:
            source = None
            callers = False
            category = "next_batch" if line.startswith(("Next:", "Batch:")) else "other"
        counts[category] += len(raw)
    characters = len(text)
    return {
        "characters": characters,
        "tokens_est": estimate_tokens(text),
        "characters_by_category": counts,
        "share_pct": {key: 100 * value / max(1, characters) for key, value in counts.items()},
        "line_prefix_characters": prefixes,
        "line_prefix_share_pct": 100 * prefixes / max(1, characters),
        "test_caller_characters": test_callers,
    }


def audit(
    repo: Path, requests: Path, ref: str = "HEAD", budget: int | None = 2000
) -> dict[str, Any]:
    start = time.perf_counter()
    metadata = provenance(repo, ref)
    metadata["budget"] = budget if budget is not None else "adaptive, cap 2000"
    spec = json.loads(requests.read_text(encoding="utf-8"))
    rows = []
    with tempfile.TemporaryDirectory(prefix="prism-packet-audit-") as temp:
        base = Path(temp)
        with (
            isolated_environment(base),
            historical_store(repo, base, metadata["source_head"]) as store,
        ):
            for request in spec["requests"]:
                pack = op_task(store, request["query"], budget, use_cache=False)
                text = render_task(pack)
                rows.append(
                    {
                        **request,
                        **composition(text),
                        "packet": text,
                        "confidence": pack["confidence"],
                        "sufficient": pack.get("sufficient"),
                    }
                )
    characters = sum(row["characters"] for row in rows)
    categories = {
        key: sum(row["characters_by_category"][key] for row in rows)
        for key in rows[0]["characters_by_category"]
    }
    return {
        **metadata,
        "index_revision": "HEAD",
        "request_set": spec,
        "rows": rows,
        "summary": {
            "requests": len(rows),
            "characters": characters,
            "mean_packet_tokens": sum(row["tokens_est"] for row in rows) / len(rows),
            "share_pct": {key: 100 * value / characters for key, value in categories.items()},
            "line_prefix_share_pct": 100
            * sum(row["line_prefix_characters"] for row in rows)
            / characters,
            "test_caller_share_pct": 100
            * sum(row["test_caller_characters"] for row in rows)
            / max(1, categories["callers"]),
        },
        "elapsed_seconds": time.perf_counter() - start,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--requests", type=Path, default=REQUESTS)
    parser.add_argument("--ref", default="HEAD", help="Pin the audited source revision.")
    parser.add_argument(
        "--adaptive", action="store_true", help="Audit the default shared budget ladder."
    )
    parser.add_argument("--output", type=Path, default=ROOT / "output/benchmarks/packet_audit.json")
    args = parser.parse_args()
    report = audit(args.repo.resolve(), args.requests, args.ref, None if args.adaptive else 2000)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
