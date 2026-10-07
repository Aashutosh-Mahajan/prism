"""Answers come from the working tree, whether or not the agent ran `prism update`."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from prism.cli import app
from prism.incremental.lock import LockBusy, UpdateLock
from prism.lifecycle import apply_init, plan_init, scan, set_paused, update
from prism.mcp.server import PrismTools
from prism.navigator.freshness import refresh_if_stale
from prism.navigator.store import IndexStore
from prism.status import compute_status
from prism.writers.manifest import load_manifest

DISCOUNTS = "src/shop/pricing/discounts.py"
runner = CliRunner()


def snapshot(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file() and "cache" not in p.relative_to(root).parts
    }


@pytest.fixture
def repo(small_repo: Path) -> Path:
    apply_init(plan_init(small_repo))
    scan(small_repo)
    return small_repo


def edit(repo: Path, marker: str = "zephyr_marker") -> None:
    path = repo / DISCOUNTS
    path.write_text(path.read_text() + f"\n\ndef {marker}():\n    return 'fresh'\n")


def test_mcp_task_sees_an_edit_the_agent_never_announced(repo: Path) -> None:
    tools = PrismTools(repo)
    try:
        assert tools.prism_task("zephyr_marker")["blocks"] == []
        edit(repo)
        assert compute_status(repo).modified == [DISCOUNTS]  # the index is behind the tree
        pack = tools.prism_task("zephyr_marker")
        assert pack["stale_sources"] == 0
        assert pack["blocks"][0]["symbol"] == "shop.pricing.discounts.zephyr_marker"
        assert "return 'fresh'" in pack["blocks"][0]["source"]
        assert compute_status(repo).fresh
    finally:
        if tools._store:
            tools._store.close()


def test_cli_navigation_sees_an_unannounced_edit(repo: Path) -> None:
    edit(repo)
    result = runner.invoke(app, ["task", "zephyr_marker", "--root", str(repo), "--json"])
    assert result.exit_code == 0, result.output
    assert (
        json.loads(result.output)["blocks"][0]["symbol"] == "shop.pricing.discounts.zephyr_marker"
    )
    located = runner.invoke(app, ["locate", "zephyr_marker", "--root", str(repo), "--json"])
    assert located.exit_code == 0 and "zephyr_marker" in located.output


def test_new_and_deleted_files_are_picked_up(repo: Path) -> None:
    (repo / "src/shop/brand_new.py").write_text("def quokka_feature():\n    return 1\n")
    (repo / "src/shop/legacy.py").unlink()
    assert refresh_if_stale(repo) == 2
    store = IndexStore.open(repo)
    try:
        assert store.symbol("shop.brand_new.quokka_feature") is not None
        assert not store.file_exists("src/shop/legacy.py")
    finally:
        store.close()


def test_nothing_changed_means_no_work_and_no_writes(repo: Path) -> None:
    before = snapshot(repo)
    assert refresh_if_stale(repo) == 0
    assert snapshot(repo) == before


def test_without_consent_queries_read_but_never_write(repo: Path) -> None:
    from prism.consent import registry_path

    registry_path().unlink()  # a teammate's committed index; PRISM is not enabled for this user
    edit(repo)
    before = snapshot(repo)
    assert refresh_if_stale(repo) == 0
    result = runner.invoke(app, ["task", "apply_discount", "--root", str(repo)])
    assert result.exit_code == 0
    assert snapshot(repo) == before


def test_paused_queries_do_not_update(repo: Path) -> None:
    set_paused(repo, True)
    edit(repo)
    before = snapshot(repo)
    assert refresh_if_stale(repo) == 0
    assert snapshot(repo) == before


def test_a_huge_change_is_left_for_an_explicit_update(repo: Path) -> None:
    edit(repo)
    assert refresh_if_stale(repo, max_files=0) == 0
    assert compute_status(repo).modified == [DISCOUNTS]


def test_a_failing_refresh_never_breaks_a_query(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    edit(repo)

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("disk on fire")

    monkeypatch.setattr("prism.lifecycle.update", boom)
    assert refresh_if_stale(repo) == 0
    result = runner.invoke(app, ["task", "apply_discount", "--root", str(repo)])
    assert result.exit_code == 0


def test_update_lock_serializes_and_reports_contention(repo: Path) -> None:
    with UpdateLock(repo):
        with pytest.raises(LockBusy):
            UpdateLock(repo, wait=0.1).__enter__()
        edit(repo)
        assert refresh_if_stale(repo, wait=0.1) == 0  # busy: leave it to the holder
    assert refresh_if_stale(repo) == 1  # released: the guard now does it


def test_a_crashed_updaters_lock_is_taken_over(repo: Path) -> None:
    lock = repo / ".aicontext" / "cache" / "update.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("99999 0\n")
    old = time.time() - 3600
    os.utime(lock, (old, old))
    with UpdateLock(repo, wait=0.2):
        pass
    assert not lock.exists()


def test_concurrent_updaters_end_with_a_consistent_index(repo: Path) -> None:
    for i in range(4):
        (repo / f"src/shop/burst_{i}.py").write_text(f"def burst_{i}():\n    return {i}\n")
    errors: list[BaseException] = []

    def work() -> None:
        try:
            update(repo)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert compute_status(repo).fresh
    incremental = {p: e["sha256"] for p, e in (load_manifest(repo) or {})["files"].items()}
    scan(repo, full=True)
    assert {p: e["sha256"] for p, e in (load_manifest(repo) or {})["files"].items()} == incremental


def test_session_remembers_returned_code_across_cli_calls(repo: Path) -> None:
    args = ["task", "apply_discount", "--root", str(repo), "--session", "s1", "--json"]
    first = json.loads(runner.invoke(app, args).output)
    again = json.loads(runner.invoke(app, args).output)
    other = json.loads(runner.invoke(app, [*args[:-3], "--session", "s2", "--json"]).output)
    assert any("source" in b for b in first["blocks"])
    assert all(b.get("seen") and "source" not in b for b in again["blocks"])
    assert any("source" in b for b in other["blocks"])  # a different session sees it afresh


def test_compact_brief_drops_overview_and_placeholders(repo: Path) -> None:
    compact = json.loads(runner.invoke(app, ["brief", "--root", str(repo), "--json"]).output)
    full = json.loads(runner.invoke(app, ["brief", "--root", str(repo), "--full", "--json"]).output)
    assert compact["compact"] and not full["compact"]
    assert "Not written yet" not in compact["brief"] and "Top modules" not in compact["brief"]
    assert "Top modules" in full["brief"]
    assert len(compact["brief"]) < len(full["brief"]) / 2


def test_written_narrative_survives_into_the_compact_brief(repo: Path) -> None:
    path = repo / ".aicontext" / "AGENTS.md"
    text = path.read_text(encoding="utf-8")
    start = text.index("<!-- prism:narrative:purpose -->")
    end = text.index("<!-- /prism:narrative:purpose -->")
    path.write_text(
        text[:start] + "<!-- prism:narrative:purpose -->\nPrices shopping carts.\n" + text[end:],
        encoding="utf-8",
    )
    compact = json.loads(runner.invoke(app, ["brief", "--root", str(repo), "--json"]).output)
    assert "Purpose: Prices shopping carts." in compact["brief"]
    assert "Architecture" not in compact["brief"]  # still a placeholder, so not injected
