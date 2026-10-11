"""Historical prose and raw scores cannot become retrieval context."""

from contextlib import closing
from pathlib import Path

from prism.lifecycle import apply_init, plan_init, scan
from prism.navigator.find import run_find
from prism.navigator.store import IndexStore


def test_repository_archive_rules_exclude_source_and_text(small_repo: Path):
    rules = Path(__file__).resolve().parents[2] / ".prismignore"
    (small_repo / ".prismignore").write_bytes(rules.read_bytes())
    for relative in (
        "docs/archive/old.py",
        "docs/archive/old.md",
        "docs/benchmarks/raw.json",
        "docs/benchmarks/run/raw.jsonl",
    ):
        path = small_repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("obsolete_archive_unique_marker", encoding="utf-8")
    live = small_repo / "docs/current.md"
    live.write_text("live_evidence_unique_marker", encoding="utf-8")
    apply_init(plan_init(small_repo))
    scan(small_repo)
    with closing(IndexStore.open(small_repo)) as store:
        assert "docs/archive/old.py" not in store.manifest["files"]
        result = run_find(store, ["obsolete_archive_unique_marker"])
        assert result["results"][0]["total"] == 0
        assert run_find(store, ["live_evidence_unique_marker"])["results"][0]["total"] == 1
