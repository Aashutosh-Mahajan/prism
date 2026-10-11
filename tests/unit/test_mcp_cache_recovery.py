from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from prism.mcp.server import PrismTools
from prism.navigator import cache_db


def test_real_writer_contention_does_not_purge_caches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "shared.sqlite"
    writer = sqlite3.connect(path)
    writer.execute("CREATE TABLE items (value INTEGER)")
    writer.execute("BEGIN IMMEDIATE")
    reader = sqlite3.connect(path, timeout=0.01)
    monkeypatch.setattr(
        cache_db, "purge_disposable_caches", lambda root: pytest.fail("contention purged caches")
    )
    tools = PrismTools(tmp_path)
    try:
        result = tools.call(lambda: dict(reader.execute("INSERT INTO items VALUES (1)")))
        assert result["error"] == "index_busy"
        assert result["retryable"] is True
        assert path.is_file()
    finally:
        reader.close()
        writer.rollback()
        writer.close()


def test_real_corrupt_database_retries_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "broken.sqlite"
    path.write_bytes(b"this is not a sqlite database" * 50)
    attempts = 0
    purged: list[Path] = []
    monkeypatch.setattr(cache_db, "purge_disposable_caches", lambda root: purged.append(root))

    def query():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            conn = sqlite3.connect(path)
            try:
                conn.execute("SELECT * FROM sqlite_master").fetchall()
            finally:
                conn.close()
        return {"ok": True}

    assert PrismTools(tmp_path).call(query) == {"ok": True}
    assert attempts == 2
    assert purged == [tmp_path]


def test_non_corruption_sql_error_is_not_repaired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cache_db, "purge_disposable_caches", lambda root: pytest.fail("SQL error purged caches")
    )
    conn = sqlite3.connect(":memory:")
    try:
        result = PrismTools(tmp_path).call(lambda: dict(conn.execute("SELECT * FROM missing")))
        assert result["error"] == "index_error"
        assert result["cause"] == "OperationalError"
        assert not result["retryable"]
        assert "bounded local search" in result["message"]
    finally:
        conn.close()
