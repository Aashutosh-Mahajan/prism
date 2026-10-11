from __future__ import annotations

from pathlib import Path

import pytest

from prism.lifecycle import apply_init, plan_init, scan
from prism.navigator.api import op_task
from prism.navigator.store import IndexStore
from prism.writers.task_cache import source_stamp


@pytest.fixture
def indexed(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "main.py").write_text('def message():\n    return "coppermoon"\n', encoding="utf-8")
    apply_init(plan_init(root))
    scan(root)
    return root


def total(pack: dict) -> int:
    return next(lit["total"] for lit in pack["literals"] if lit["text"] == "coppermoon")


def test_new_unquoted_locale_invalidates_packet_and_evidence_memo(indexed: Path) -> None:
    store = IndexStore.open(indexed)
    try:
        query = "find 'coppermoon'"
        first = op_task(store, query, 2000)
        assert total(first) == 1
        before = source_stamp(indexed, store.manifest)
        (indexed / "locale.json").write_text('{"message":"coppermoon"}', encoding="utf-8")
        after = source_stamp(indexed, store.manifest)
        assert before != after
        assert total(op_task(store, query, 2000)) == 2
        (indexed / "locale.json").unlink()
        assert total(op_task(store, query, 2000)) == 1
    finally:
        store.close()


def test_existing_unquoted_file_gaining_match_invalidates_cache(indexed: Path) -> None:
    path = indexed / "locale.json"
    path.write_text('{"message":"silvermoon"}', encoding="utf-8")
    store = IndexStore.open(indexed)
    try:
        query = "find 'coppermoon'"
        assert total(op_task(store, query, 2000)) == 1
        path.write_text('{"message":"coppermoon"}', encoding="utf-8")
        assert total(op_task(store, query, 2000)) == 2
    finally:
        store.close()


def test_new_source_disables_cache_until_manifest_catches_up(indexed: Path) -> None:
    store = IndexStore.open(indexed)
    try:
        assert source_stamp(indexed, store.manifest)
        (indexed / "new.py").write_text("def unseen():\n    return 42\n", encoding="utf-8")
        assert source_stamp(indexed, store.manifest) is None
        pack = op_task(store, "find 'coppermoon'", 2000)
        assert not pack["sufficient"]
        assert pack["search_limited"]
        assert all(not lit["complete"] for lit in pack.get("literals", []))
    finally:
        store.close()
