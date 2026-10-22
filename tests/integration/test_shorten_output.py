"""`prism hook shorten-output`: long Bash output shortened for Claude Code, failures always kept."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prism.hooks.output import shorten_output
from prism.integrations import IntegrationOptions, get_integration
from prism.lifecycle import apply_init, plan_init, scan


@pytest.fixture
def enabled(small_repo: Path) -> Path:
    apply_init(plan_init(small_repo))
    scan(small_repo)
    return small_repo


def payload(root: Path, command: str, stdout: str, tool: str = "Bash") -> str:
    return json.dumps(
        {
            "cwd": str(root),
            "hook_event_name": "PostToolUse",
            "tool_name": tool,
            "tool_input": {"command": command},
            "tool_response": {
                "stdout": stdout,
                "stderr": "",
                "interrupted": False,
                "isImage": False,
            },
        }
    )


def pytest_output(passed: int) -> str:
    lines = [f"tests/test_m.py::test_{i} PASSED" for i in range(passed)]
    lines += [
        "=================================== FAILURES ===================================",
        "___________________________________ test_bad ___________________________________",
        "E       AssertionError: assert 1 == 2",
        "=========================== short test summary info ============================",
        "FAILED tests/test_m.py::test_bad - AssertionError: assert 1 == 2",
        f"======================== 1 failed, {passed} passed in 0.50s ========================",
    ]
    return "\n".join(lines)


def test_long_test_output_is_shortened_and_failures_kept(enabled: Path) -> None:
    out = shorten_output(payload(enabled, "python -m pytest -v", pytest_output(200)))
    result = json.loads(out)["hookSpecificOutput"]
    assert result["hookEventName"] == "PostToolUse"
    replaced = result["updatedToolOutput"]
    # The replacement keeps the Bash output shape, or Claude Code ignores it.
    assert set(replaced) == {"stdout", "stderr", "interrupted", "isImage"}
    assert "AssertionError: assert 1 == 2" in replaced["stdout"]
    assert "1 failed, 200 passed" in replaced["stdout"]
    assert "test_150 PASSED" not in replaced["stdout"]
    saved = replaced["stdout"].rsplit("full output: ", 1)[1].rstrip("]")
    assert "test_150 PASSED" in Path(saved).read_text(encoding="utf-8")  # nothing is lost


def test_short_output_and_other_tools_are_left_alone(enabled: Path) -> None:
    assert shorten_output(payload(enabled, "python -m pytest", pytest_output(3))) == ""
    assert shorten_output(payload(enabled, "cat a.py", pytest_output(200), tool="Read")) == ""
    assert shorten_output("not json") == ""


def test_switched_off_and_without_consent(enabled: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRISM_SHORTEN_OUTPUT", "0")
    assert shorten_output(payload(enabled, "python -m pytest -v", pytest_output(200))) == ""


def test_installed_only_when_asked(tmp_path: Path) -> None:
    def post_tool_use(options: IntegrationOptions) -> list[dict[str, object]]:
        changes = get_integration("claude-code").plan(tmp_path, options)
        settings = next(c for c in changes if c.path == ".claude/settings.json")
        return json.loads(settings.content or "{}")["hooks"]["PostToolUse"]

    assert [e["matcher"] for e in post_tool_use(IntegrationOptions())] == ["Edit|Write|MultiEdit"]
    entries = post_tool_use(IntegrationOptions(shorten_output=True))
    assert [e["matcher"] for e in entries] == ["Edit|Write|MultiEdit", "Bash"]
    assert entries[1]["hooks"][0]["command"] == "prism hook shorten-output"
