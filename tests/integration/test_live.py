"""Live paired runs: both copies run, tokens are accounted separately, quality is checked."""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from prism.core.errors import UserError
from prism.lifecycle import apply_init, plan_init, scan
from prism.viewer.live import ACTIVE, LiveRunner, _empty_arm, compare, usage_totals

FAKE = Path(__file__).parents[1] / "fixtures/fake_claude.py"
CHECK = (
    f'"{sys.executable}" -c "import sys; sys.path.insert(0, \'src\'); '
    'from shop.money import Money; assert (Money(5) - Money(2)).cents == 3"'
)


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PRISM_CONFIG_HOME", str(tmp_path / "config"))
    repo = shutil.copytree(Path(__file__).parents[1] / "fixtures/repos/small", tmp_path / "repo")
    apply_init(plan_init(repo))
    scan(repo)

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    git("init")
    git("add", "src", "tests")
    git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-m", "fixture")
    return repo


def wait(runner: LiveRunner) -> dict:
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        snapshot = runner.snapshot()
        if snapshot and snapshot["state"] not in ACTIVE:
            return snapshot
        time.sleep(0.3)
    raise AssertionError("live run did not finish")


def runner_for(root: Path) -> LiveRunner:
    return LiveRunner(root, root / ".aicontext/cache/live", {"claude": [sys.executable, str(FAKE)]})


def test_usage_totals_count_cached_input_as_processed() -> None:
    totals = usage_totals(
        {
            "input_tokens": 1,
            "cache_creation_input_tokens": 2,
            "cache_read_input_tokens": 3,
            "output_tokens": 4,
        }
    )
    assert totals == {
        "input_tokens": 1,
        "cache_creation_tokens": 2,
        "cache_read_tokens": 3,
        "output_tokens": 4,
        "input_total": 6,
        "total_tokens": 10,
    }
    assert usage_totals(None) is None


def test_live_run_streams_both_arms_and_preserves_quality(root: Path) -> None:
    runner = runner_for(root)
    runner.start({"task": "Add a subtract method to Money", "check_command": CHECK})
    snapshot = wait(runner)
    assert snapshot["state"] == "completed", snapshot["error"]
    without, with_ = snapshot["arms"]["without"], snapshot["arms"]["with"]
    assert without["state"] == with_["state"] == "completed"
    assert any(e["kind"] == "tool" for e in without["events"])
    assert without["usage"]["total_tokens"] == 10800 and with_["usage"]["total_tokens"] == 700
    assert "__sub__" in without["patch"] and "__sub__" in with_["patch"]
    assert without["check"]["passed"] and with_["check"]["passed"]
    assert snapshot["verdict"]["quality"] == "same"
    assert snapshot["verdict"]["token_saving_pct"] == pytest.approx(93.5, abs=0.1)
    assert snapshot["verdict"]["cost_saving_pct"] == pytest.approx(80.0)
    assert snapshot["verdict"]["identical_patch"]
    # Only the With copy received PRISM; the original repository was never touched.
    directory = Path(snapshot["preparation"]["arms"]["with"])
    assert (directory / ".claude/settings.json").is_file()
    assert not (Path(snapshot["preparation"]["arms"]["without"]) / ".claude").exists()
    assert "__sub__" not in (root / "src/shop/money.py").read_text(encoding="utf-8")


def test_degraded_solution_is_reported_not_hidden(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_BREAK", "with")
    runner = runner_for(root)
    runner.start({"task": "Add a subtract method to Money", "check_command": CHECK})
    snapshot = wait(runner)
    assert snapshot["arms"]["without"]["check"]["passed"]
    assert not snapshot["arms"]["with"]["check"]["passed"]
    assert snapshot["verdict"]["quality"] == "degraded"
    assert snapshot["verdict"]["token_saving_pct"] is not None  # saving is shown, never as success


def test_without_a_check_quality_is_unverified(root: Path) -> None:
    runner = runner_for(root)
    runner.start({"task": "Add a subtract method to Money"})
    assert wait(runner)["verdict"]["quality"] == "unverified"


def test_validation_and_missing_agent(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = runner_for(root)
    for body in (
        {},
        {"task": " "},
        {"task": "x", "max_turns": 0},
        {"task": "x", "model": "bad model!"},
        {"task": "x", "check_command": "a\nb"},
    ):
        with pytest.raises(UserError):
            runner.start(body)
    monkeypatch.setenv("PRISM_CLAUDE_BIN", "")
    monkeypatch.setattr("prism.viewer.live.shutil.which", lambda *a, **k: None)
    monkeypatch.setattr("prism.viewer.live.glob.glob", lambda *a, **k: [])
    with pytest.raises(UserError, match="not found"):
        LiveRunner(root, root / "cache").start({"task": "x", "agent": "claude"})


def test_compare_never_invents_numbers_for_an_incomplete_run() -> None:
    arm = {**_empty_arm(), "state": "failed"}
    result = compare({"without": dict(arm), "with": dict(arm)}, True)
    assert result["quality"] == "incomplete" and result["token_saving_pct"] is None
