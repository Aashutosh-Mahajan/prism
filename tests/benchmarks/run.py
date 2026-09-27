"""Repeatable local performance report: python -m tests.benchmarks.run --packages 20.

Uses an isolated temporary repository and consent registry. Nothing in the user's
repository is initialized. --enforce is intended for a dedicated benchmark runner.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any

from prism.lifecycle import apply_init, plan_init, scan, update
from prism.navigator.api import op_context
from prism.navigator.store import IndexStore
from tests.benchmarks.synth import generate


def benchmark(packages: int, modules: int, functions: int) -> dict[str, Any]:
    previous = os.environ.get("PRISM_CONFIG_HOME")
    with tempfile.TemporaryDirectory(prefix="prism-benchmark-") as temp:
        base = Path(temp)
        os.environ["PRISM_CONFIG_HOME"] = str(base / "config")
        try:
            root = base / "repo"
            loc = generate(root, packages, modules, functions)
            apply_init(plan_init(root))
            start = time.perf_counter()
            manifest = scan(root)
            scan_s = time.perf_counter() - start
            start = time.perf_counter()
            update(root)
            unchanged_s = time.perf_counter() - start
            edited = root / "app" / "p0" / "m0.py"
            edited.write_text(
                edited.read_text(encoding="utf-8") + "\n# benchmark edit\n", encoding="utf-8"
            )
            start = time.perf_counter()
            result = update(root, files=["app/p0/m0.py"])
            update_s = time.perf_counter() - start
            store = IndexStore.open(root)
            try:
                samples = []
                for _ in range(25):
                    start = time.perf_counter()
                    op_context(store, "app.p0.m0.f0_0_0")
                    samples.append(time.perf_counter() - start)
            finally:
                store.close()
            return {
                "generated_module_loc": loc,
                "stats": manifest["stats"],
                "scan_seconds": round(scan_s, 4),
                "unchanged_update_seconds": round(unchanged_s, 4),
                "one_file_update_seconds": round(update_s, 4),
                "reparsed": result.reparsed,
                "context_median_ms": round(statistics.median(samples) * 1000, 2),
                "context_p95_ms": round(sorted(samples)[23] * 1000, 2),
                "update_target_met": update_s <= 0.5,
                "query_target_met": sorted(samples)[23] <= 0.2,
            }
        finally:
            if previous is None:
                os.environ.pop("PRISM_CONFIG_HOME", None)
            else:
                os.environ["PRISM_CONFIG_HOME"] = previous


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packages", type=int, default=20)
    parser.add_argument("--modules", type=int, default=20)
    parser.add_argument("--functions", type=int, default=10)
    parser.add_argument("--enforce", action="store_true")
    args = parser.parse_args()
    if min(args.packages, args.modules, args.functions) < 1:
        parser.error("dimensions must be positive")
    report = benchmark(args.packages, args.modules, args.functions)
    print(json.dumps(report, indent=2))
    if args.enforce and not (report["update_target_met"] and report["query_target_met"]):
        raise SystemExit(1)
