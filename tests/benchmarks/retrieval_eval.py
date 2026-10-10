"""Retrieval quality: does one `prism task` call contain where the change belongs?

    python -m tests.benchmarks.retrieval_eval [--tier core|stretch|paraphrase|all] [--json]

Each case is a request and the file:line locations an edit for it would touch. A case is
*located* when every location appears in the answer: as an exact literal occurrence, inside a
returned block, or as a call site. The score is the share of locations found, and the tokens the
answer cost. It runs on fixture repositories, offline, in a few seconds, so any change to
ranking can be judged by it. Cases marked `stretch` are known to be hard; they are reported,
not required.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
FIXTURES = HERE.parent / "fixtures" / "repos"
CASES = HERE / "retrieval_cases.json"


def covered(pack: dict[str, Any], file: str, line: int) -> bool:
    """Is `file:line` in the answer?"""
    for lit in pack.get("literals", []):
        if any(o["file"] == file and o["line"] == line for o in lit["occurrences"]):
            return True
    for block in pack["blocks"]:
        start, end = block["lines"]
        if block["file"] == file and start <= line <= end and "source" in block:
            return True
    return any(
        link["role"] == "caller" and link["file"] == file and link.get("line") == line
        for link in pack.get("links", [])
    )


def load_cases(tier: str = "all") -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = json.loads(CASES.read_text(encoding="utf-8"))
    return [c for c in cases if tier == "all" or c["tier"] == tier]


def index_fixture(name: str, workdir: Path) -> Path:
    from prism.lifecycle import apply_init, plan_init, scan

    root = shutil.copytree(FIXTURES / name, workdir / name)
    apply_init(plan_init(root))
    scan(root)
    return root


def evaluate(
    tier: str = "all", budget: int = 2000, *, semantic: bool = False
) -> list[dict[str, Any]]:
    """Run every case; one row per case with what was found and what it cost."""
    from prism.navigator.api import op_task
    from prism.navigator.store import IndexStore

    if semantic:
        from prism.navigator.semantic import DEFAULT_MODEL, get_embedder

        get_embedder(DEFAULT_MODEL)  # fail explicitly rather than measuring a silent fallback

    rows: list[dict[str, Any]] = []
    previous = os.environ.get("PRISM_CONFIG_HOME")
    previous_semantic = os.environ.get("PRISM_SEMANTIC")
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["PRISM_CONFIG_HOME"] = str(Path(tmp) / "cfg")  # never the real registry
        os.environ["PRISM_SEMANTIC"] = "1" if semantic else "0"
        stores: dict[str, IndexStore] = {}
        try:
            for case in load_cases(tier):
                name = case["repo"]
                if name not in stores:
                    stores[name] = IndexStore.open(index_fixture(name, Path(tmp)))
                    if semantic:
                        from prism.navigator.semantic import warm_vectors

                        warm_vectors(stores[name].root)
                pack = op_task(stores[name], case["query"], budget)
                found = [loc for loc in case["expect"] if covered(pack, loc[0], loc[1])]
                rows.append(
                    {
                        "repo": name,
                        "tier": case["tier"],
                        "kind": case["kind"],
                        "query": case["query"][:60],
                        "found": len(found),
                        "expected": len(case["expect"]),
                        "located": len(found) == len(case["expect"]),
                        "tokens": pack["budget"]["used_est"],
                        "confidence": pack["confidence"],
                        "missing": [loc for loc in case["expect"] if loc not in found],
                        "top3_locations": sum(
                            any(
                                b["file"] == file
                                and b["lines"][0] <= line <= b["lines"][1]
                                and "source" in b
                                for b in pack["blocks"][:3]
                            )
                            for file, line in case["expect"]
                        ),
                        "semantic": semantic,
                    }
                )
        finally:
            for store in stores.values():
                store.close()
            if previous is None:
                os.environ.pop("PRISM_CONFIG_HOME", None)
            else:
                os.environ["PRISM_CONFIG_HOME"] = previous
            if previous_semantic is None:
                os.environ.pop("PRISM_SEMANTIC", None)
            else:
                os.environ["PRISM_SEMANTIC"] = previous_semantic
    return rows


def summarise(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Located share and mean tokens, overall and per query kind."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups["all"].append(row)
        groups[row["kind"]].append(row)
    return {
        key: {
            "cases": len(group),
            "located": sum(r["located"] for r in group) / len(group),
            "locations": sum(r["found"] for r in group) / max(1, sum(r["expected"] for r in group)),
            "tokens": statistics.fmean(r["tokens"] for r in group),
            "top3_recall": sum(r.get("top3_locations", 0) for r in group)
            / max(1, sum(r["expected"] for r in group)),
        }
        for key, group in sorted(groups.items())
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--tier", default="core", choices=["core", "stretch", "paraphrase", "all"])
    parser.add_argument("--budget", type=int, default=2000)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--semantic",
        action="store_true",
        help="Evaluate the installed local model; never download.",
    )
    args = parser.parse_args(argv)
    rows = evaluate(args.tier, args.budget, semantic=args.semantic)
    if args.json:
        print(json.dumps({"rows": rows, "summary": summarise(rows)}, indent=2))
        return
    for row in rows:
        mark = "ok  " if row["located"] else "MISS"
        print(
            f"{mark} {row['kind']:<10} {row['found']}/{row['expected']} {row['tokens']:>5} tok  {row['query']}"
        )
        for loc in row["missing"]:
            print(f"       missing {loc[0]}:{loc[1]}")
    print()
    print(f"{'kind':<12}{'cases':>6}{'located':>9}{'locations':>11}{'mean tokens':>13}")
    for key, s in summarise(rows).items():
        print(
            f"{key:<12}{s['cases']:>6.0f}{s['located']:>9.0%}{s['locations']:>11.0%}{s['tokens']:>13.0f}"
        )


if __name__ == "__main__":
    main()
