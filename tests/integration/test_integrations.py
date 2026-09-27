from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from prism.integrations import IntegrationOptions, detect_agents
from prism.integrations.global_note import install_global, uninstall_global
from prism.lifecycle import apply_init, apply_uninstall, plan_init, plan_uninstall


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


def test_cursor_and_codex(tiny_repo: Path) -> None:
    install(tiny_repo, "cursor")
    rule = (tiny_repo / ".cursor" / "rules" / "prism.mdc").read_text(encoding="utf-8")
    assert rule.startswith("---\ndescription:") and "alwaysApply: true" in rule
    assert "PRISM Codebase Audit" in rule and "PRISM Narrative Refresh" in rule
    assert json.loads((tiny_repo / ".cursor" / "mcp.json").read_text())["mcpServers"]["prism"][
        "args"
    ] == ["mcp"]
    install(tiny_repo, "codex")
    assert "PRISM code index" in (tiny_repo / "AGENTS.md").read_text()
    apply_uninstall(tiny_repo, plan_uninstall(tiny_repo))
    assert not (tiny_repo / ".cursor" / "rules" / "prism.mdc").exists()
    assert not (tiny_repo / "AGENTS.md").exists()


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
