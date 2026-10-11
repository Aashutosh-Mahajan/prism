from __future__ import annotations

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from prism.cache_cleanup import cache_size, collect_tee
from prism.cli import app


def test_500_logs_respect_all_limits_and_preserve_other_artifacts(
    tmp_path: Path, monkeypatch
) -> None:
    from prism import outputfilter

    directory = tmp_path / ".aicontext/cache/tee"
    directory.mkdir(parents=True)
    monkeypatch.setattr(outputfilter, "tee_dir", lambda root: directory)
    for number in range(500):
        path = directory / f"123456-{number:08x}.txt"
        path.write_bytes(b"x" * 100)
        metadata = path.with_suffix(".meta.json")
        metadata.write_bytes(b"{}")
        os.utime(path, (number, number))
        os.utime(metadata, (number, number))
    index = tmp_path / ".aicontext/call_graph.json"
    index.write_bytes(b"index")
    note = tmp_path / ".aicontext/README.md"
    note.write_bytes(b"notes")
    unknown = directory / "owner.txt"
    unknown.write_bytes(b"keep")
    result = collect_tee(tmp_path, keep=40, max_bytes=1020, age_days=1 / 86400 * 100, now=500)
    assert result["kept_logs"] == 10 and result["kept_bytes"] == 1020
    assert result["removed_files"] == 980 and result["removed_bytes"] == 49980
    assert index.read_bytes() == b"index" and note.read_bytes() == b"notes"
    assert unknown.read_bytes() == b"keep"
    assert sorted(p.stem for p in directory.glob("*.txt") if p != unknown) == [
        f"123456-{n:08x}" for n in range(490, 500)
    ]
    assert (
        collect_tee(tmp_path, keep=40, max_bytes=1020, age_days=100 / 86400, now=500)[
            "removed_files"
        ]
        == 0
    )


def test_age_orphan_metadata_and_oversized_logs(tmp_path: Path, monkeypatch) -> None:
    from prism import outputfilter

    monkeypatch.setattr(outputfilter, "tee_dir", lambda root: tmp_path)
    old = tmp_path / "123456-00000001.txt"
    old.write_bytes(b"old")
    os.utime(old, (0, 0))
    (tmp_path / "123456-00000002.meta.json").write_bytes(b"{}")
    (tmp_path / "123456-00000003.txt").write_bytes(b"x" * 101)
    result = collect_tee(tmp_path, max_bytes=100, age_days=1, now=100000)
    assert result["removed_files"] == 3 and result["kept_logs"] == 0


def test_cli_reports_cleanup_and_size(tmp_path: Path, monkeypatch) -> None:
    from prism import consent, outputfilter

    monkeypatch.setattr(outputfilter, "tee_dir", lambda root: tmp_path / "tee")
    monkeypatch.setattr(consent, "cache_root", lambda root: tmp_path)
    (tmp_path / "query.db").write_bytes(b"untouched")
    result = CliRunner().invoke(app, ["cache", "gc", "--root", str(tmp_path), "--json"])
    assert result.exit_code == 0, result.output
    assert '"cache_bytes": 9' in result.output
    assert cache_size(tmp_path) == (1, 9)
    assert (tmp_path / "query.db").read_bytes() == b"untouched"


def test_symlink_directory_never_reads_writes_or_deletes_target(
    tmp_path: Path, monkeypatch
) -> None:
    from prism import consent, outputfilter

    target = tmp_path / "owner"
    target.mkdir()
    log = target / "123456-00000001.txt"
    log.write_bytes(b"owner log")
    link = tmp_path / "cache"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("creating symlinks requires Windows developer mode or privilege")
    monkeypatch.setattr(outputfilter, "tee_dir", lambda root: link)
    monkeypatch.setattr(consent, "cache_root", lambda root: link)
    assert collect_tee(tmp_path, keep=0)["unsafe_path"]
    assert cache_size(tmp_path) == (0, 0)
    assert outputfilter.save_tee(tmp_path, "pytest", "new") is None
    assert log.read_bytes() == b"owner log"


def test_oversized_output_is_not_saved_then_evicted(tmp_path: Path, monkeypatch) -> None:
    from prism import outputfilter

    monkeypatch.setattr(outputfilter, "tee_dir", lambda root: tmp_path)
    assert outputfilter.save_tee(tmp_path, "pytest", "", raw=b"x" * (32 * 1024 * 1024)) is None
    assert not list(tmp_path.glob("*.txt"))
