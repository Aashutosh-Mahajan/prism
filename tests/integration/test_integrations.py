from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from prism.integrations import IntegrationOptions, detect_agents
from prism.integrations.global_note import install_global, uninstall_global
from prism.lifecycle import apply_init, apply_uninstall, plan_init, plan_uninstall

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


def snapshot(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file()
        and ".aicontext" not in p.relative_to(root).parts
        and ".git" not in p.relative_to(root).parts
    }


def install(root: Path, agent: str, **opts: bool) -> None:
    apply_init(plan_init(root, [agent], IntegrationOptions(**opts)))


def test_detect_agents(tmp_path: Path) -> None:
    assert detect_agents(tmp_path) == ["generic"]
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".cursor").mkdir()
    assert detect_agents(tmp_path) == ["claude-code", "cursor"]


def test_claude_code_install_contents(tiny_repo: Path) -> None:
    install(tiny_repo, "claude-code")
    for name in ("prism-context", "prism-refresh", "prism-audit"):
        text = (tiny_repo / ".claude" / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
        assert "prism-managed" in text and f"name: {name}" in text
    settings = json.loads((tiny_repo / ".claude" / "settings.json").read_text())
    session = settings["hooks"]["SessionStart"][0]
    assert session["hooks"][0]["command"] == "prism hook session-start"
    prompt = settings["hooks"]["UserPromptSubmit"][0]
    assert prompt["hooks"][0]["command"] == "prism hook user-prompt"
    assert "matcher" not in prompt  # UserPromptSubmit has no matcher
    post = settings["hooks"]["PostToolUse"][0]
    assert post["matcher"] == "Edit|Write|MultiEdit"
    assert post["hooks"][0]["command"] == "prism hook post-edit"
    mcp = json.loads((tiny_repo / ".mcp.json").read_text())
    assert mcp["mcpServers"]["prism"] == {"command": "prism", "args": ["mcp"]}
    claude_md = (tiny_repo / "CLAUDE.md").read_text()
    assert claude_md.startswith("<!-- prism-managed:start -->")
    assert "Never run `prism init`" in claude_md


def test_install_is_idempotent_and_merges_user_config(tiny_repo: Path) -> None:
    (tiny_repo / ".claude").mkdir()
    user_settings = {
        "permissions": {"allow": ["Bash(ls)"]},
        "hooks": {
            "PostToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo hi"}]}
            ]
        },
    }
    (tiny_repo / ".claude" / "settings.json").write_text(json.dumps(user_settings))
    (tiny_repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))
    (tiny_repo / "CLAUDE.md").write_text("# My rules\n\nBe nice.\n")
    install(tiny_repo, "claude-code")
    settings = json.loads((tiny_repo / ".claude" / "settings.json").read_text())
    assert settings["permissions"] == {"allow": ["Bash(ls)"]}
    commands = [h["hooks"][0]["command"] for h in settings["hooks"]["PostToolUse"]]
    assert commands == ["echo hi", "prism hook post-edit"]
    assert set(json.loads((tiny_repo / ".mcp.json").read_text())["mcpServers"]) == {
        "other",
        "prism",
    }
    assert (tiny_repo / "CLAUDE.md").read_text().startswith("# My rules\n\nBe nice.\n")

    before = snapshot(tiny_repo)
    plan = plan_init(tiny_repo, ["claude-code"], IntegrationOptions())
    assert plan.file_changes == ()
    install(tiny_repo, "claude-code")
    assert snapshot(tiny_repo) == before


def test_uninstall_restores_original_bytes(tiny_repo: Path) -> None:
    (tiny_repo / ".claude").mkdir()
    (tiny_repo / ".claude" / "settings.json").write_text('{"model":   "x"}\n')
    (tiny_repo / "CLAUDE.md").write_text("# Mine\r\n")
    before = snapshot(tiny_repo)
    install(tiny_repo, "claude-code")
    assert snapshot(tiny_repo) != before
    apply_uninstall(tiny_repo, plan_uninstall(tiny_repo))
    after = snapshot(tiny_repo)
    # .gitignore lines belong to the index itself (init), not the integration; --purge removes them.
    after.pop(".gitignore")
    assert after == before


def test_uninstall_is_surgical_after_user_edits(tiny_repo: Path) -> None:
    install(tiny_repo, "claude-code")
    claude_md = tiny_repo / "CLAUDE.md"
    claude_md.write_text(claude_md.read_text() + "\n# Added later by the user\n")
    apply_uninstall(tiny_repo, plan_uninstall(tiny_repo))
    assert claude_md.read_text() == "# Added later by the user\n"
    assert not (tiny_repo / ".mcp.json").exists()
    assert not (tiny_repo / ".claude" / "skills" / "prism-context").exists() or not any(
        (tiny_repo / ".claude" / "skills" / "prism-context").iterdir()
    )


def test_opt_outs(tiny_repo: Path) -> None:
    install(tiny_repo, "claude-code", hooks=False, mcp=False)
    assert not (tiny_repo / ".mcp.json").exists()
    assert not (tiny_repo / ".claude" / "settings.json").exists()
    assert (tiny_repo / ".claude" / "skills" / "prism-audit" / "SKILL.md").is_file()


def test_cursor_rules_are_small_and_procedures_are_on_request(tiny_repo: Path) -> None:
    install(tiny_repo, "cursor")
    rules = tiny_repo / ".cursor" / "rules"
    always = (rules / "prism.mdc").read_text(encoding="utf-8")
    assert always.startswith("---\ndescription:") and "alwaysApply: true" in always
    assert "prism task" in always
    # Sent on every turn, so it carries only how to start; procedures are asked for by description.
    assert "Codebase Audit" not in always and len(always) < 1500
    for name in ("prism-audit", "prism-refresh", "prism-decisions"):
        text = (rules / f"{name}.mdc").read_text(encoding="utf-8")
        assert "alwaysApply: false" in text and "description:" in text
    assert json.loads((tiny_repo / ".cursor" / "mcp.json").read_text())["mcpServers"]["prism"][
        "args"
    ] == ["mcp"]
    hooks = json.loads((tiny_repo / ".cursor" / "hooks.json").read_text())
    assert hooks["version"] == 1
    assert hooks["hooks"]["sessionStart"] == [
        {"command": "prism hook session-start --format cursor"}
    ]
    assert hooks["hooks"]["afterFileEdit"] == [{"command": "prism hook post-edit"}]


def test_cursor_hooks_keep_the_users_own(tiny_repo: Path) -> None:
    (tiny_repo / ".cursor").mkdir()
    mine = {"version": 1, "hooks": {"afterFileEdit": [{"command": "./format.sh"}]}}
    (tiny_repo / ".cursor" / "hooks.json").write_text(json.dumps(mine))
    install(tiny_repo, "cursor")
    merged = json.loads((tiny_repo / ".cursor" / "hooks.json").read_text())
    assert [h["command"] for h in merged["hooks"]["afterFileEdit"]] == [
        "./format.sh",
        "prism hook post-edit",
    ]
    apply_uninstall(tiny_repo, plan_uninstall(tiny_repo))
    assert json.loads((tiny_repo / ".cursor" / "hooks.json").read_text()) == mine


def test_codex_install_contents(tiny_repo: Path) -> None:
    install(tiny_repo, "codex")
    assert "PRISM code index" in (tiny_repo / "AGENTS.md").read_text()
    config = (tiny_repo / ".codex" / "config.toml").read_text()
    assert "[mcp_servers.prism]" in config and 'args = ["mcp"]' in config
    parsed = tomllib.loads(config)
    assert parsed["mcp_servers"]["prism"]["command"] == "prism"
    hooks = json.loads((tiny_repo / ".codex" / "hooks.json").read_text())["hooks"]
    assert hooks["UserPromptSubmit"][0]["hooks"][0]["command"] == "prism hook user-prompt"
    assert hooks["PostToolUse"][0]["matcher"] == "apply_patch|Edit|Write"
    assert hooks["SessionStart"][0]["hooks"][0]["command"] == "prism hook session-start"
    plan = plan_init(tiny_repo, ["codex"], IntegrationOptions())
    assert plan.file_changes == ()  # idempotent


def test_codex_never_declares_the_users_prism_server_twice(tiny_repo: Path) -> None:
    (tiny_repo / ".codex").mkdir()
    mine = '[mcp_servers.prism]\ncommand = "my-prism"\nargs = ["serve"]\n\n[model]\nname = "x"\n'
    (tiny_repo / ".codex" / "config.toml").write_text(mine)
    install(tiny_repo, "codex")
    after = (tiny_repo / ".codex" / "config.toml").read_text()
    assert after == mine
    assert tomllib.loads(after)["mcp_servers"]["prism"]["command"] == "my-prism"


def test_codex_toml_merge_and_exact_restore(tiny_repo: Path) -> None:
    (tiny_repo / ".codex").mkdir()
    mine = 'model = "o3"\n\n[mcp_servers.other]\ncommand = "x"\n'
    (tiny_repo / ".codex" / "config.toml").write_text(mine)
    install(tiny_repo, "codex")
    merged = tomllib.loads((tiny_repo / ".codex" / "config.toml").read_text())
    assert set(merged["mcp_servers"]) == {"other", "prism"} and merged["model"] == "o3"
    apply_uninstall(tiny_repo, plan_uninstall(tiny_repo))
    assert (tiny_repo / ".codex" / "config.toml").read_text() == mine
    assert not (tiny_repo / ".codex" / "hooks.json").exists()
    assert not (tiny_repo / "AGENTS.md").exists()


def test_codex_tells_the_user_about_project_trust(tiny_repo: Path) -> None:
    from prism.integrations import get_integration

    notes = get_integration("codex").notes(tiny_repo, IntegrationOptions())
    assert any("trust" in n.lower() for n in notes)
    assert (
        get_integration("codex").notes(tiny_repo, IntegrationOptions(hooks=False, mcp=False)) == []
    )


def test_gemini_install_contents_and_merge(tiny_repo: Path) -> None:
    (tiny_repo / ".gemini").mkdir()
    mine = {"theme": "dark", "mcpServers": {"other": {"command": "x"}}}
    (tiny_repo / ".gemini" / "settings.json").write_text(json.dumps(mine))
    install(tiny_repo, "gemini")
    settings = json.loads((tiny_repo / ".gemini" / "settings.json").read_text())
    assert settings["theme"] == "dark" and set(settings["mcpServers"]) == {"other", "prism"}
    hooks = settings["hooks"]
    assert hooks["BeforeAgent"][0]["hooks"][0]["command"] == (
        "prism hook user-prompt --format json --event BeforeAgent"
    )
    assert hooks["SessionStart"][0]["hooks"][0]["timeout"] == 10000  # milliseconds
    assert hooks["AfterTool"][0]["matcher"] == "write_file|replace"
    assert "PRISM code index" in (tiny_repo / "GEMINI.md").read_text()
    apply_uninstall(tiny_repo, plan_uninstall(tiny_repo))
    assert json.loads((tiny_repo / ".gemini" / "settings.json").read_text()) == mine
    assert not (tiny_repo / "GEMINI.md").exists()


def test_antigravity_installs_a_rule_and_prints_the_user_level_mcp_entry(tiny_repo: Path) -> None:
    from prism.integrations import get_integration

    options = IntegrationOptions()
    install(tiny_repo, "antigravity")
    rule = (tiny_repo / ".agent" / "rules" / "prism.md").read_text(encoding="utf-8")
    assert "prism task" in rule and "prism-managed" in rule
    assert (tiny_repo / ".agents" / "skills" / "prism-context" / "SKILL.md").is_file()
    (note,) = get_integration("antigravity").notes(tiny_repo, options)
    assert ".gemini/antigravity/mcp_config.json" in note and '"prism"' in note
    # PRISM never edits user-level config on its own.
    assert not any(
        c.path.startswith(("~", "/")) for c in plan_init(tiny_repo, ["antigravity"]).file_changes
    )
    apply_uninstall(tiny_repo, plan_uninstall(tiny_repo))
    assert not (tiny_repo / ".agent" / "rules" / "prism.md").exists()


@pytest.mark.parametrize(
    "agent", ["claude-code", "cursor", "codex", "gemini", "antigravity", "generic"]
)
def test_every_agent_is_idempotent_reversible_and_leaves_user_files_alone(
    tiny_repo: Path, agent: str
) -> None:
    mine = {
        "AGENTS.md": "# Team rules\n\nBe kind.\n",
        "CLAUDE.md": "# Mine\n",
        "GEMINI.md": "# Gemini mine\n",
    }
    for name, text in mine.items():
        (tiny_repo / name).write_text(text)
    before = snapshot(tiny_repo)
    install(tiny_repo, agent)
    once = snapshot(tiny_repo)
    install(tiny_repo, agent)
    assert snapshot(tiny_repo) == once  # a second init changes nothing
    apply_uninstall(tiny_repo, plan_uninstall(tiny_repo))
    after = snapshot(tiny_repo)
    after.pop(".gitignore", None)  # belongs to the index itself, not the integration
    assert after == before


def test_detect_finds_every_agent_that_is_present(tmp_path: Path) -> None:
    for marker in (".claude", ".cursor", ".codex", ".gemini", ".agent"):
        (tmp_path / marker).mkdir()
    assert detect_agents(tmp_path) == ["claude-code", "cursor", "codex", "gemini", "antigravity"]


def test_hook_commands_in_every_config_are_ones_the_cli_accepts(tiny_repo: Path) -> None:
    """A hook entry that names a flag `prism hook` does not know would silently never work."""
    import re
    import shlex

    from prism.hooks.entry import HOOKS, parse_flags

    for agent in ("claude-code", "cursor", "codex", "gemini"):
        install(tiny_repo, agent)
    text = "\n".join(
        p.read_text(encoding="utf-8")
        for p in tiny_repo.rglob("*")
        if p.is_file() and p.suffix in {".json"} and ".aicontext" not in p.parts
    )
    commands = set(re.findall(r'"command": "(prism hook [^"]+)"', text))
    assert len(commands) >= 5
    for command in commands:
        words = shlex.split(command)
        assert words[2] in HOOKS, command
        flags = parse_flags(words[3:])
        assert set(flags) <= {"format", "event"}, command
        assert flags.get("format", "text") in ("text", "json", "cursor"), command


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def test_git_hooks_install_and_remove(tiny_repo: Path) -> None:
    _git(tiny_repo, "init", "-q")
    hooks = tiny_repo / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    (hooks / "post-commit").write_text("#!/bin/sh\necho mine\n")
    apply_init(plan_init(tiny_repo, [], git_hooks=True))
    text = (hooks / "post-commit").read_text()
    assert text.startswith("#!/bin/sh\necho mine\n") and "prism update --quiet" in text
    assert "prism update --quiet" in (hooks / "post-merge").read_text()
    apply_uninstall(tiny_repo, plan_uninstall(tiny_repo))
    assert (hooks / "post-commit").read_text() == "#!/bin/sh\necho mine\n"
    assert not (hooks / "post-merge").exists()


def test_purge_removes_index_and_consent(tiny_repo: Path) -> None:
    from prism.consent import get_entry

    install(tiny_repo, "generic")
    assert get_entry(tiny_repo) is not None
    apply_uninstall(tiny_repo, plan_uninstall(tiny_repo), purge=True)
    assert not (tiny_repo / ".aicontext").exists()
    assert get_entry(tiny_repo) is None
    assert not (tiny_repo / ".gitignore").exists()


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


def test_global_note(fake_home: Path) -> None:
    target = fake_home / ".claude" / "CLAUDE.md"
    target.parent.mkdir()
    target.write_text("# Global rules\n")
    install_global()
    text = target.read_text()
    assert "Never run `prism init`" in text and "mention PRISM once" not in text
    install_global(suggest=True)
    assert "mention PRISM once" in target.read_text()
    uninstall_global()
    assert target.read_text() == "# Global rules\n"
