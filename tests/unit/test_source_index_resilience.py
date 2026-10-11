from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from prism.navigator import source_index
from prism.navigator.source_index import SOURCE_DB, SourceIndex, pending_files
from prism.navigator.store import IndexStore


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(source_index, "cache_dir", lambda root: tmp_path / "cache")
    raw = b"def coppermoon():\n    return 42\n"
    (tmp_path / "module.py").write_bytes(raw)
    manifest = {"files": {"module.py": {"sha256": hashlib.sha256(raw).hexdigest()}}}
    value = IndexStore(tmp_path.resolve(), manifest, sqlite3.connect(":memory:"))
    yield value
    value.close()


def test_failed_read_is_pending_and_retries_without_manifest_change(
    store: IndexStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_read = source_index.read_indexed_source
    with monkeypatch.context() as patch:
        patch.setattr(source_index, "read_indexed_source", lambda *args: None)
        with SourceIndex(store) as index:
            assert index.paths_with("coppermoon") == set()
        assert pending_files(store.root, store.manifest) == 1
    with SourceIndex(store) as index:
        assert index.paths_with("coppermoon") == {"module.py"}
    assert pending_files(store.root, store.manifest) == 0
    assert real_read(store, "module.py") is not None


def test_hash_mismatch_recovers_when_indexed_bytes_return(store: IndexStore) -> None:
    path = store.root / "module.py"
    original = path.read_bytes()
    path.write_bytes(b"def silvermoon():\n    return 99\n")
    with SourceIndex(store) as index:
        assert index.paths_with("silvermoon") == set()
    path.write_bytes(original)
    with SourceIndex(store) as index:
        assert index.paths_with("coppermoon") == {"module.py"}


def test_warm_read_does_not_require_writer_lock(
    store: IndexStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    with SourceIndex(store):
        pass
    blocker = sqlite3.connect(source_index.cache_dir(store.root) / SOURCE_DB)
    blocker.execute("BEGIN IMMEDIATE")
    real_connect = sqlite3.connect

    def quick_connect(*args, **kwargs):
        kwargs["timeout"] = 0.05
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(source_index.sqlite3, "connect", quick_connect)
    try:
        with SourceIndex(store) as index:
            assert index.paths_with("coppermoon") == {"module.py"}
    finally:
        blocker.rollback()
        blocker.close()


def test_empty_verified_file_is_not_retried(
    store: IndexStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    (store.root / "module.py").write_bytes(b"")
    store.manifest["files"]["module.py"]["sha256"] = hashlib.sha256(b"").hexdigest()
    with SourceIndex(store):
        pass
    monkeypatch.setattr(
        source_index,
        "read_indexed_source",
        lambda *args: pytest.fail("verified empty file retried"),
    )
    with SourceIndex(store):
        pass


def test_changed_and_deleted_postings_are_replaced(store: IndexStore) -> None:
    with SourceIndex(store):
        pass
    raw = b"def silvermoon():\n    return 99\n"
    (store.root / "module.py").write_bytes(raw)
    store.manifest["files"]["module.py"]["sha256"] = hashlib.sha256(raw).hexdigest()
    with SourceIndex(store) as index:
        assert not index.paths_with("coppermoon")
        assert index.paths_with("silvermoon") == {"module.py"}
    del store.manifest["files"]["module.py"]
    with SourceIndex(store) as index:
        assert not index.paths_with("silvermoon")


def test_source_reader_pins_snapshot_across_other_generation(store: IndexStore) -> None:
    import copy

    old = SourceIndex(store)
    manifest = copy.deepcopy(store.manifest)
    raw = b"def silvermoon():\n    return 99\n"
    (store.root / "module.py").write_bytes(raw)
    manifest["files"]["module.py"]["sha256"] = hashlib.sha256(raw).hexdigest()
    current = IndexStore(store.root, manifest, sqlite3.connect(":memory:"))
    try:
        with SourceIndex(current) as index:
            assert index.paths_with("silvermoon") == {"module.py"}
        assert old.paths_with("coppermoon") == {"module.py"}
        assert not old.paths_with("silvermoon")
    finally:
        old.close()
        current.close()
