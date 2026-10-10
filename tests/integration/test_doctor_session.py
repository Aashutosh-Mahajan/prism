"""`prism doctor --session`: was PRISM used in an agent session, and if not, why not."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from prism.cli import app
from prism.hooks import user_prompt
from prism.lifecycle import apply_init, plan_init, scan
from prism.maintenance import session_report


@pytest.fixture
def enabled(small_repo: Path) -> Path:
    apply_init(plan_init(small_repo))
    scan(small_repo)
    return small_repo


def hook(root: Path, session: str, prompt: str) -> str:
    payload = json.dumps({"cwd": str(root), "session_id": session, "prompt": prompt})
    return user_prompt(payload, time_budget=30, inline_build=True)


def by_name(root: Path, session: str) -> dict[str, tuple[str, str]]:
    return {c.name: (c.status, c.detail) for c in session_report(root, session)}


def test_an_unknown_session_is_reported_not_guessed(enabled: Path) -> None:
    status, detail = by_name(enabled, "nobody")["session"]
    assert status == "warn" and "no work log" in detail


def test_a_session_the_hook_answered_is_a_used_session(enabled: Path) -> None:
    hook(enabled, "s1", "where is apply_discount and what calls it")
    checks = by_name(enabled, "s1")
    assert checks["hook"][0] == "ok" and checks["verdict"][0] == "ok"


def test_a_greeting_shows_why_the_hook_added_nothing(enabled: Path) -> None:
    hook(enabled, "s2", "thanks")
    checks = by_name(enabled, "s2")
    assert checks["hook"][0] == "warn" and "not a request" in checks["hook"][1]
    assert checks["verdict"][0] == "fail"


def test_tool_calls_count_as_use_even_without_the_hook(enabled: Path) -> None:
    CliRunner().invoke(
        app,
        ["task", "where is apply_discount", "--root", str(enabled), "--session", "s3"],
    )
    checks = by_name(enabled, "s3")
    assert checks["tool calls"][0] == "ok" and "cli" in checks["tool calls"][1]
    assert checks["hook"][0] == "fail" and "never fired" in checks["hook"][1]
    assert checks["verdict"][0] == "ok"


def test_the_command_line_reports_the_latest_session(enabled: Path) -> None:
    hook(enabled, "s4", "where is apply_discount and what calls it")
    result = CliRunner().invoke(app, ["doctor", "--root", str(enabled), "--session", "latest"])
    assert result.exit_code == 0 and "PRISM was used" in result.output
