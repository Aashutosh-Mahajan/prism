from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from prism.discovery import scanner
from prism.navigator import textcorpus
from prism.navigator.textcorpus import TEXT_DB, TextCorpus


def test_text_discovery_does_not_rehash_unchanged_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(textcorpus, "cache_dir", lambda root: tmp_path / "cache")
    monkeypatch.setattr(scanner, "recent_text_listing", lambda root: None)
    code = tmp_path / "module.py"
    raw = b"def coppermoon():\n    return 42\n"
    code.write_bytes(raw)
    stat = code.stat()
    manifest = {
        "files": {
            "module.py": {
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size": stat.st_size,
                "mtime": stat.st_mtime,
                "language": "python",
            }
        }
    }
    (tmp_path / "locale.json").write_text('{"message": "coppermoon"}', encoding="utf-8")
    monkeypatch.setattr(
        scanner, "hash_file", lambda path: pytest.fail("text listing rehashed code")
    )
    corpus = TextCorpus(tmp_path, manifest)
    try:
        assert corpus.paths_with("coppermoon") == {"locale.json"}
    finally:
        corpus.close()


def test_warm_text_query_does_not_require_writer_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(textcorpus, "cache_dir", lambda root: tmp_path / "cache")
    monkeypatch.setattr(scanner, "recent_text_listing", lambda root: None)
    (tmp_path / "locale.json").write_text('{"message": "coppermoon"}', encoding="utf-8")
    TextCorpus(tmp_path, {}).close()
    blocker = sqlite3.connect(tmp_path / "cache" / TEXT_DB)
    blocker.execute("BEGIN IMMEDIATE")
    real_connect = sqlite3.connect

    def quick_connect(*args, **kwargs):
        kwargs["timeout"] = 0.05
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(textcorpus.sqlite3, "connect", quick_connect)
    try:
        corpus = TextCorpus(tmp_path, {})
        try:
            assert corpus.paths_with("coppermoon") == {"locale.json"}
        finally:
            corpus.close()
    finally:
        blocker.rollback()
        blocker.close()


def test_text_reader_pins_snapshot_across_other_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(textcorpus, "cache_dir", lambda root: tmp_path / "cache")
    monkeypatch.setattr(scanner, "recent_text_listing", lambda root: None)
    path = tmp_path / "locale.json"
    path.write_text('{"message":"coppermoon"}', encoding="utf-8")
    old = TextCorpus(tmp_path, {})
    try:
        path.write_text('{"message":"silvermoon"}', encoding="utf-8")
        current = TextCorpus(tmp_path, {})
        try:
            assert current.paths_with("silvermoon") == {"locale.json"}
        finally:
            current.close()
        assert old.paths_with("coppermoon") == {"locale.json"}
        assert not old.paths_with("silvermoon")
    finally:
        old.close()
