from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from prism.core.errors import IndexStaleError
from prism.lifecycle import apply_init, plan_init, scan, update
from prism.navigator import cache_db
from prism.navigator.store import IndexStore
from prism.writers.manifest import load_manifest


@pytest.fixture
def indexed(small_repo: Path) -> Path:
    apply_init(plan_init(small_repo))
    scan(small_repo)
    return small_repo


def logical_rows(conn: sqlite3.Connection, table: str) -> list:
    if table == "docs":
        sql = "SELECT kind,ref,length FROM docs"
    elif table == "postings":
        sql = "SELECT d.kind,d.ref,p.term,p.tf FROM postings p JOIN docs d USING(doc_id)"
    elif table == "search_facts":
        sql = "SELECT d.kind,d.ref,s.digest FROM search_facts s JOIN docs d USING(doc_id)"
    else:
        sql = f"SELECT * FROM {table}"
    return sorted(tuple(r) for r in conn.execute(sql))


def test_delta_generation_equals_full_build_and_keeps_old_reader(indexed: Path) -> None:
    old = IndexStore.open(indexed)
    original = old.all_symbols()
    file = indexed / "src/shop/new_service.py"
    file.write_text("def coppermoon(amount):\n    return amount * 2\n", encoding="utf-8")
    update(indexed)
    current = IndexStore.open(indexed)
    full = sqlite3.connect(":memory:")
    try:
        assert old.all_symbols() == original
        assert (
            current.conn.execute("SELECT value FROM meta WHERE key='build_mode'").fetchone()[0]
            == "delta"
        )
        cache_db._build(full, indexed / ".aicontext", current.manifest)
        tables = [
            r[0]
            for r in full.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if r[0] != "meta"
        ]
        for table in tables:
            assert logical_rows(current.conn, table) == logical_rows(full, table), table
        assert current.search("coppermoon")[0].ref.endswith("coppermoon")
    finally:
        full.close()
        current.close()
        old.close()


def test_delta_does_not_retokenize_unchanged_documents(
    indexed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = cache_db.term_counts
    calls = []

    def count(fields):
        calls.append(fields)
        return original(fields)

    monkeypatch.setattr(cache_db, "term_counts", count)
    (indexed / "src/shop/new_service.py").write_text(
        "def coppermoon():\n    return 42\n", encoding="utf-8"
    )
    update(indexed)
    current = IndexStore.open(indexed)
    try:
        count_docs = current.conn.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
        assert calls and len(calls) < count_docs / 2
    finally:
        current.close()


def test_cache_rejects_mixed_artifact_generation(indexed: Path) -> None:
    manifest = load_manifest(indexed)
    assert manifest is not None
    (cache_db.cache_dir(indexed) / f"index-{cache_db.fingerprint(manifest)}.sqlite").unlink()
    path = indexed / ".aicontext/symbols.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["symbols"] = []
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(IndexStaleError):
        IndexStore.open(indexed)
    assert not list(cache_db.cache_dir(indexed).glob(".index-*.tmp"))


def test_delete_generation_removes_search_documents(indexed: Path) -> None:
    path = indexed / "src/shop/pricing/discounts.py"
    old = IndexStore.open(indexed)
    old.close()
    path.unlink()
    update(indexed)
    current = IndexStore.open(indexed)
    try:
        assert not current.symbols_in_file("src/shop/pricing/discounts.py")
        assert not any(
            "discounts.apply_discount" in hit.ref for hit in current.search("apply_discount")
        )
    finally:
        current.close()


def test_open_retries_generation_retired_between_check_and_connect(
    indexed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = load_manifest(indexed)
    assert manifest is not None
    path = cache_db.cache_dir(indexed) / f"index-{cache_db.fingerprint(manifest)}.sqlite"
    original = sqlite3.connect
    retired = False

    def connect(database, *args, **kwargs):
        nonlocal retired
        if str(database).startswith(f"file:{path.as_posix()}?") and not retired:
            retired = True
            path.unlink()
        return original(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    store = IndexStore.open(indexed)
    try:
        assert retired and store.all_symbols()
    finally:
        store.close()


def test_duplicate_relative_routes_preserve_handlers_across_generations(tmp_path: Path) -> None:
    for module, handler in (("first", "coppermoon"), ("second", "silverleaf")):
        (tmp_path / f"{module}.py").write_text(
            f"from django.urls import path\n\ndef {handler}():\n    return 42\n\n"
            f"urlpatterns = [path('invoices/', {handler})]\n",
            encoding="utf-8",
        )
    apply_init(plan_init(tmp_path))
    scan(tmp_path)
    old = IndexStore.open(tmp_path)
    try:
        assert len(old.routes()) == 2
        for handler in ("coppermoon", "silverleaf"):
            assert any(h.kind == "route" and h.ref == "ANY /invoices/" for h in old.search(handler))
        (tmp_path / "second.py").unlink()
        update(tmp_path)
        current = IndexStore.open(tmp_path)
        full = sqlite3.connect(":memory:")
        try:
            assert len(old.routes()) == 2 and len(current.routes()) == 1
            assert not any(h.kind == "route" for h in current.search("silverleaf"))
            assert (
                current.conn.execute("SELECT value FROM meta WHERE key='build_mode'").fetchone()[0]
                == "delta"
            )
            cache_db._build(full, tmp_path / ".aicontext", current.manifest)
            for table in ("docs", "search_facts", "postings", "routes"):
                assert logical_rows(current.conn, table) == logical_rows(full, table)
        finally:
            current.close()
            full.close()
    finally:
        old.close()
