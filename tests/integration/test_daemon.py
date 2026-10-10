"""The warm query process: same bytes as in-process, consent-bound, and never started uninvited."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from prism.cli import app
from prism.lifecycle import apply_init, plan_init, scan, set_paused
from prism.navigator import daemon

QUERY = "where is apply_discount and what calls it"


@pytest.fixture
def enabled(small_repo: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    apply_init(plan_init(small_repo))
    scan(small_repo)
    monkeypatch.setenv("PRISM_DAEMON", "1")
    yield_root = small_repo
    return yield_root


def task(root: Path, query: str = QUERY) -> str:
    result = CliRunner().invoke(app, ["task", query, "--root", str(root)])
    assert result.exit_code == 0, result.output
    return result.output


def wait_for(predicate: object, seconds: float = 20.0) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if predicate():  # type: ignore[operator]
            return True
        time.sleep(0.2)
    return False


def test_first_call_answers_in_process_then_a_warm_process_answers_identically(
    enabled: Path,
) -> None:
    try:
        first = task(enabled)  # no process yet: answered in-process, and one is started
        assert wait_for(lambda: daemon._read_info(enabled) is not None)
        assert wait_for(
            lambda: (
                daemon.ask(
                    enabled,
                    {
                        "op": "task",
                        "query": QUERY,
                        "budget": 2000,
                        "mode": "auto",
                        "session": None,
                        "json": False,
                    },
                )
                is not None
            )
        )
        warm = task(enabled)
        assert warm == first
        as_json = CliRunner().invoke(app, ["task", QUERY, "--root", str(enabled), "--json"])
        assert as_json.exit_code == 0 and as_json.output.strip().startswith("{")
    finally:
        daemon.stop(enabled)


def test_pausing_stops_the_warm_process(enabled: Path) -> None:
    try:
        task(enabled)
        assert wait_for(lambda: daemon._read_info(enabled) is not None)
        set_paused(enabled, True)
        assert wait_for(lambda: daemon._read_info(enabled) is None, 10.0)
        assert daemon.ask(enabled, {"op": "task", "query": QUERY}) is None
    finally:
        daemon.stop(enabled)


def test_nothing_is_started_for_a_repo_that_is_not_enabled(
    small_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRISM_DAEMON", "1")
    assert not daemon.enabled(small_repo)  # not initialised
    daemon.ensure_running(small_repo)
    assert not (small_repo / ".aicontext").exists()


def test_it_can_be_switched_off(enabled: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRISM_DAEMON", "0")
    assert not daemon.enabled(enabled)
    task(enabled)
    assert daemon._read_info(enabled) is None


def test_a_wrong_key_is_refused(enabled: Path) -> None:
    try:
        task(enabled)
        assert wait_for(lambda: daemon._read_info(enabled) is not None)
        info = dict(daemon._read_info(enabled) or {})
        info["key"] = "00" * 24
        assert daemon._call(info, {"op": "task", "query": QUERY}) is None
    finally:
        daemon.stop(enabled)


@pytest.mark.skipif(sys.platform == "win32", reason="named pipes have no path limit")
def test_a_deep_checkout_gets_a_short_socket_path(tmp_path: Path) -> None:
    deep = tmp_path.joinpath(*["very-long-directory-name"] * 6)
    deep.mkdir(parents=True)
    assert len(daemon._address(deep).encode("utf-8")) <= 104
