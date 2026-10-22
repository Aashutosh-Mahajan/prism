"""Live comparison agents: Antigravity's stream, command lines and the With PRISM environment."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from prism.viewer.live import AGENTS, AntigravityStream, LiveRunner, _prism_shim


def _feed(stream: AntigravityStream, *messages: dict) -> list:
    return [stream.feed(m) for m in messages]


def test_antigravity_stream_reports_text_tools_commands_and_totals() -> None:
    stream = AntigravityStream()
    step = lambda **kw: {"event": "step_update", "step_update": kw}  # noqa: E731
    updates = _feed(
        stream,
        {"event": "init", "init": {"permission_mode": "accept-edits"}},
        step(step_index=1, state="DONE", step_type="agent_response",
             usage={"input_tokens": 100, "output_tokens": 10}),
        step(step_index=2, state="ACTIVE", step_type="tool", tool_name="read_file",
             tool_info={"parameters": {"Path": "a.py"}}),
        step(step_index=3, state="ACTIVE", step_type="tool", tool_name="run_command",
             tool_info={"parameters": {"CommandLine": "pytest"}}),
        step(step_index=3, state="ERROR", step_type="tool", tool_name="run_command",
             tool_info={"parameters": {"CommandLine": "pytest"}, "error": {"message": "denied"}}),
        step(step_index=4, state="ACTIVE", step_type="agent_response", text_delta="Done "),
        step(step_index=4, state="DONE", step_type="agent_response", text_delta="now.",
             usage={"input_tokens": 120, "output_tokens": 20}),
        {"event": "result", "result": {"status": "SUCCESS", "response": "Done now.", "num_turns": 2,
         "usage": {"input_tokens": 220, "cache_read_tokens": 5, "output_tokens": 30},
         "denied_actions": [{"action": "command"}]}},
    )
    events = [e for u in updates for e in u.events]
    assert [e["kind"] for e in events] == [
        "info", "tool", "terminal_start", "terminal_end", "text", "info",
    ]
    assert events[3] == {"kind": "terminal_end", "id": "3", "output": "denied", "ok": False}
    assert events[4]["text"] == "Done now."
    assert updates[-2].usage["total_tokens"] == 100 + 10 + 120 + 20  # running total of steps
    final = updates[-1]
    assert final.done and final.final and not final.failed
    assert final.usage == {
        "input_tokens": 220, "cache_creation_tokens": 0, "cache_read_tokens": 5,
        "output_tokens": 30, "input_total": 225, "total_tokens": 255,
    }
    assert final.turns == 2


def test_antigravity_error_result_fails_the_run() -> None:
    update = AntigravityStream().feed(
        {"event": "result", "result": {"status": "ERROR", "error": "empty prompt"}}
    )
    assert update.done and update.failed == "empty prompt"


def test_antigravity_command_carries_the_task_even_when_it_starts_with_a_dash() -> None:
    agent = AGENTS["antigravity"]
    command = agent.command(["agy"], "claude-sonnet-4-6", 10, Path("."), "-fix the bug")
    assert command[0] == "agy" and command[1].startswith("--print=-fix the bug")
    assert command[-2:] == ["--model", "claude-sonnet-4-6"]
    assert not agent.stdin_prompt and not agent.manual


def test_codex_command_avoids_the_elevated_windows_sandbox_and_trusts_a_with_copy(tmp_path: Path) -> None:
    (tmp_path / ".codex").mkdir()
    command = AGENTS["codex"].command(["codex"], "", 10, tmp_path, "task")
    config = [command[i + 1] for i, a in enumerate(command) if a == "-c"]
    assert any(c.endswith('.trust_level="trusted"') for c in config)
    assert any(c.startswith("mcp_servers.prism.command=") for c in config)
    if sys.platform == "win32":
        assert 'windows.sandbox="unelevated"' in config
    plain = AGENTS["codex"].command(["codex"], "", 10, tmp_path / "other", "task")
    assert not any("prism" in a for a in plain)


def test_claude_with_copy_gets_its_mcp_config(tmp_path: Path) -> None:
    without = AGENTS["claude"].command(["claude"], "", 10, tmp_path, "task")
    assert "--mcp-config" not in without
    (tmp_path / ".mcp.json").write_text("{}")
    with_prism = AGENTS["claude"].command(["claude"], "", 10, tmp_path, "task")
    assert with_prism[with_prism.index("--mcp-config") + 1] == str(tmp_path / ".mcp.json")
    assert "mcp__prism" in with_prism[with_prism.index("--allowedTools") + 1]


def test_with_arm_finds_prism_from_a_plain_shell_and_the_baseline_does_not(tmp_path: Path) -> None:
    runner = LiveRunner.__new__(LiveRunner)
    with_env = runner._env(tmp_path / "config", with_prism=True)
    shim = Path(with_env["PATH"].split(";" if sys.platform == "win32" else ":")[0])
    assert shim == tmp_path / "config" / "bin" and (shim / "prism").is_file()
    assert (shim / "prism.cmd").is_file()
    if sys.platform != "win32":
        out = subprocess.run([str(shim / "prism"), "--version"], capture_output=True, text=True)
        assert out.returncode == 0 and "prism" in out.stdout
    assert str(shim) not in runner._env(tmp_path / "config-empty", with_prism=False)["PATH"]
    assert json.loads('"ok"') == "ok"
    _prism_shim(tmp_path / "again")


def test_codex_hook_trust_is_skipped_only_for_prism_own_hooks(tmp_path: Path) -> None:
    hooks = tmp_path / ".codex" / "hooks.json"
    hooks.parent.mkdir()
    entry = lambda c: {"hooks": [{"hooks": [{"type": "command", "command": c}]}] }  # noqa: E731
    hooks.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"command": "prism hook stop"}]}]}}))
    assert "--dangerously-bypass-hook-trust" in AGENTS["codex"].command(["codex"], "", 5, tmp_path, "t")
    hooks.write_text(
        json.dumps({"hooks": {"Stop": [{"hooks": [{"command": "prism hook stop"}, {"command": "curl x"}]}]}})
    )
    assert "--dangerously-bypass-hook-trust" not in AGENTS["codex"].command(["codex"], "", 5, tmp_path, "t")
    assert entry("x")
