"""Offline architecture probes on generated code; never initializes the owner's repository.

Run: python tests/benchmarks/architecture_probe.py --output <report.json>
These are diagnostic microbenchmarks, not agent-success or billing measurements.
"""

from __future__ import annotations

import argparse
import cProfile
import hashlib
import json
import platform
import pstats
import sqlite3
import statistics
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from prism.config import PrismConfig  # noqa: E402
from prism.core.models import SourceFile  # noqa: E402
from prism.navigator.api import op_task  # noqa: E402
from prism.navigator.cache_db import _build  # noqa: E402
from prism.navigator.source_index import SourceIndex  # noqa: E402
from prism.navigator.store import IndexStore  # noqa: E402
from prism.pipeline import build_index  # noqa: E402
from prism.writers.artifacts import build_docs  # noqa: E402
from prism.writers.task_cache import source_stamp  # noqa: E402


def measure(fn, repeats: int = 7) -> dict[str, float]:
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000)
    return {"median_ms": round(statistics.median(samples), 3), "max_ms": round(max(samples), 3)}


def probe(root: Path, count: int) -> dict:
    root.mkdir()
    out = root / ".aicontext"
    out.mkdir()
    files = []
    for number in range(count):
        path = root / f"module_{number}.py"
        raw = f"def calculate_{number}(amount):\n    return amount * 2\n".encode()
        path.write_bytes(raw)
        stat = path.stat()
        files.append(
            SourceFile(
                path.name, "python", len(raw), hashlib.sha256(raw).hexdigest(), stat.st_mtime
            )
        )
    start = time.perf_counter()
    index = build_index(root, PrismConfig(), files=files)
    cold_ms = (time.perf_counter() - start) * 1000
    cached = {parsed.path: parsed for parsed in index.parsed}
    pipeline = measure(lambda: build_index(root, PrismConfig(), files=files, cached=cached), 3)
    docs = build_docs(index)
    for name, data in docs.items():
        (out / name).write_text(json.dumps(data), encoding="utf-8")
    manifest = {
        "files": {
            f.path: {"sha256": f.sha256, "size": f.size, "mtime": f.mtime, "language": f.language}
            for f in files
        },
        "artifacts": {},
        "stats": {"files": count, "symbols": len(index.symbols)},
    }
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _build(conn, out, manifest)
    store = IndexStore(root.resolve(), manifest, conn)
    try:

        def source_query():
            with SourceIndex(store) as body:
                body.paths_with("amount")

        source_query()
        warm = measure(source_query)
        profiles = []
        for query, mode in [
            ("calculate_0", "code"),
            ("architecture overview", "overview"),
            ("double the amount calculation", "code"),
        ]:
            profile = cProfile.Profile()
            start = time.perf_counter()
            pack = profile.runcall(op_task, store, query, None, mode=mode, use_cache=False)
            elapsed = (time.perf_counter() - start) * 1000
            stats = pstats.Stats(profile).stats
            functions = {
                name: sum(v[1] for k, v in stats.items() if k[2] == name)
                for name in ("build_task", "_size", "_sync")
            }
            profiles.append(
                {
                    "query": query,
                    "mode": mode,
                    "elapsed_ms": round(elapsed, 3),
                    "estimated_tokens": pack["budget"]["used_est"],
                    "confidence": pack["confidence"],
                    "sufficient": pack["sufficient"],
                    "calls": functions,
                }
            )
        before = source_stamp(root, manifest)
        (root / "new_locale.json").write_text(
            '{"message": "newly added literal"}', encoding="utf-8"
        )
        after = source_stamp(root, manifest)
        return {
            "files": count,
            "cold_pipeline_ms": round(cold_ms, 3),
            "all_parses_cached_pipeline": pipeline,
            "warm_source_query": warm,
            "query_profiles": profiles,
            "packet_stamp_ignores_added_text_file": before == after,
        }
    finally:
        store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    temporary_root = ROOT / "tmp"
    temporary_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="architecture-probe-", dir=temporary_root) as temporary:
        base = Path(temporary)
        with patch("prism.consent.cache_root", lambda root: root / ".aicontext" / "cache"):
            results = [probe(base / f"repo-{count}", count) for count in (100, 1000)]
    report = {
        "python": sys.version,
        "platform": platform.platform(),
        "scope": "synthetic independent Python functions; no live agent or peer timings",
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
