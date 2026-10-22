# ruff: noqa: F811
"""Agents beyond the first: terminal commands, Codex counters, Antigravity hand-off and history."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from prism.core.errors import UserError
from prism.viewer.live import AGENTS, LiveRunner
from tests.integration.test_live import CHECK, root, runner_for, wait  # noqa: F401

FAKE_CODEX = Path(__file__).parents[1] / "fixtures/fake_codex.py"
SUBTRACT = (
    '\n    def __sub__(self, other: "Money") -> "Money":\n'
    "        return Money(self.cents - other.cents)\n\n\ndef zero()"
)


def test_claude_terminal_commands_are_streamed_and_counted(root: Path) -> None:
    runner = runner_for(root)
    runner.start({"task": "Add a subtract method to Money", "check_command": CHECK})
    snapshot = wait(runner)
    for arm in ("without", "with"):
        events = snapshot["arms"][arm]["events"]
        kinds = [e["kind"] for e in events]
        assert "terminal_start" in kinds and "terminal_end" in kinds
        assert snapshot["arms"][arm]["commands_run"] == 1
        end = next(e for e in events if e["kind"] == "terminal_end")
        assert end["output"] == "2 passed" and end["ok"]
        verification = [e for e in events if e.get("phase") == "verification"]
        assert [e["kind"] for e in verification] == ["terminal_start", "terminal_end"]
        assert verification[0]["command"] == CHECK
        assert verification[1]["ok"]
        assert verification[1]["output"] == snapshot["arms"][arm]["check"]["output"]
        assert snapshot["arms"][arm]["lines_added"] == 3
    assert snapshot["verdict"]["commands_saving_pct"] == pytest.approx(0.0)


def test_codex_run_counts_cached_input_inside_input(root: Path) -> None:
    runner = LiveRunner(
        root, root / ".aicontext/cache/live", {"codex": [sys.executable, str(FAKE_CODEX)]}
    )
    runner.start({"task": "Add a subtract method", "agent": "codex", "check_command": CHECK})
    snapshot = wait(runner)
    assert snapshot["state"] == "completed", snapshot["error"]
    without, with_ = snapshot["arms"]["without"], snapshot["arms"]["with"]
    # Codex reports cached input as part of input: the total is input plus output.
    assert without["usage"]["total_tokens"] == 9300
    assert without["usage"]["cache_read_tokens"] == 5000
    assert with_["usage"]["total_tokens"] == 1040 and with_["usage"]["input_total"] == 1000
    assert (Path(snapshot["preparation"]["arms"]["with"]) / ".codex").is_dir()
    assert not (Path(snapshot["preparation"]["arms"]["without"]) / ".codex").exists()
    assert snapshot["verdict"]["quality"] == "same"
    assert snapshot["verdict"]["cost_saving_pct"] is None  # Codex reports no cost: never invented
    kinds = [e["kind"] for e in with_["events"]]
    assert "terminal_start" in kinds and "terminal_end" in kinds and "text" in kinds


def test_antigravity_without_agy_is_a_manual_handoff_with_real_checks(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(AGENTS["antigravity"], "find", lambda: None)
    runner = runner_for(root)
    runner.start({"task": "Add a subtract method", "agent": "antigravity", "check_command": CHECK})
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        snapshot = runner.snapshot()
        if snapshot and snapshot["state"] == "awaiting_manual":
            break
        time.sleep(0.3)
    else:
        raise AssertionError("never reached the manual step")
    assert [a["state"] for a in snapshot["arms"].values()] == ["manual", "manual"]
    assert "config-empty" in snapshot["manual_launch"]["without"]
    assert str(Path(sys.executable).parent) in snapshot["manual_launch"]["with"]
    assert "PRISM_CONFIG_HOME" in snapshot["manual_launch"]["with"]
    with pytest.raises(UserError, match="No source changes detected"):
        runner.finish_manual()
    assert runner.snapshot()["state"] == "awaiting_manual"
    for arm in ("without", "with"):  # the person does the task in each folder
        target = Path(snapshot["preparation"]["arms"][arm]) / "src/shop/money.py"
        target.write_text(
            target.read_text(encoding="utf-8").replace("\n\ndef zero()", SUBTRACT),
            encoding="utf-8",
        )
        if arm == "without":
            with pytest.raises(UserError, match="With PRISM"):
                runner.finish_manual()
    runner.finish_manual()
    done = wait(runner)
    assert done["state"] == "completed", done["error"]
    assert done["verdict"]["quality"] == "same"
    assert done["verdict"]["token_saving_pct"] is None  # nothing is measurable in a manual run
    assert done["verdict"]["time_saving_pct"] is None
    assert done["verdict"]["commands_saving_pct"] is None
    for arm in done["arms"].values():
        assert arm["started"] and arm["finished"] and arm["duration_seconds"] >= 0
        assert arm["commands_run"] == 0  # verifier commands are separate from agent commands
        assert any(e.get("phase") == "verification" for e in arm["events"])
    with pytest.raises(UserError):
        runner.finish_manual()


def test_manual_read_only_task_requires_explicit_unchanged_override(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(AGENTS["antigravity"], "find", lambda: None)
    runner = runner_for(root)
    runner.start({"task": "Review the code without editing", "agent": "antigravity"})
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        snapshot = runner.snapshot()
        if snapshot and snapshot["state"] == "awaiting_manual":
            break
        time.sleep(0.1)
    else:
        raise AssertionError("never reached the manual step")
    runner.finish_manual(allow_unchanged=True)
    done = wait(runner)
    assert done["state"] == "completed"
    assert done["verdict"]["quality"] == "unverified"
    assert all(a["usage"] is None for a in done["arms"].values())


def test_finished_runs_are_kept_in_history(root: Path) -> None:
    runner = runner_for(root)
    runner.start({"task": "Add a subtract method", "check_command": CHECK})
    finished = wait(runner)
    rows = runner.history()
    assert [r["id"] for r in rows] == [finished["id"]]
    assert rows[0]["verdict"]["quality"] == "same" and rows[0]["agent"] == "claude"
    assert runner.saved_run(finished["id"])["arms"]["with"]["patch"]
    again = LiveRunner(root, root / ".aicontext/cache/live")
    assert again.history()[0]["id"] == finished["id"]
    with pytest.raises(UserError):
        runner.saved_run("../x")


def test_repeats_run_the_pair_again_and_summarise(root: Path) -> None:
    runner = runner_for(root)
    first = runner.start({"task": "Add a subtract method", "check_command": CHECK, "repeats": 2})
    assert first["batch"]["index"] == 1 and first["batch"]["total"] == 2
    deadline = time.monotonic() + 240
    snapshot = wait(runner)
    while time.monotonic() < deadline and not (
        snapshot["batch"]["index"] == 2 and snapshot["state"] == "completed"
    ):
        time.sleep(0.5)
        snapshot = wait(runner)
    assert snapshot["batch"]["index"] == 2
    summary = snapshot["batch"]["summary"]
    assert summary["done"] == 2 and summary["total"] == 2 and summary["same_quality"] == 2
    assert snapshot["verdict"]["no_changes"] is False
    with pytest.raises(UserError):
        runner.start({"task": "x", "repeats": 9})
