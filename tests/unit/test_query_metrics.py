import json
from pathlib import Path

import pytest

from prism.consent import cache_root
from prism.lifecycle import apply_init, plan_init, scan
from prism.navigator.api import op_task
from prism.navigator.store import IndexStore


def test_opt_in_metrics_are_local_bounded_and_do_not_store_query_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "main.py").write_text("def coppermoon():\n    return 42\n", encoding="utf-8")
    apply_init(plan_init(root))
    scan(root)
    store = IndexStore.open(root)
    try:
        monkeypatch.delenv("PRISM_PROFILE", raising=False)
        op_task(store, "coppermoon", 2000, use_cache=False)
        path = cache_root(root) / "query-metrics.jsonl"
        assert not path.exists()
        monkeypatch.setenv("PRISM_PROFILE", "1")
        op_task(store, "coppermoon", 2000, use_cache=False)
        text = path.read_text(encoding="utf-8")
        assert "coppermoon" not in text
        row = json.loads(text)
        assert row["elapsed_ms"] >= 0
        assert row["counters"]["packet_builds"] == 1
        assert row["counters"]["packet_size_checks"] > 0
        assert "retrieval_and_fit" in row["stages_ms"]
    finally:
        store.close()
