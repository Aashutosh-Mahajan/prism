from pathlib import Path

import pytest

from prism.integrations import IntegrationOptions, get_integration


def test_mcp_server_instructions_do_not_override_hook_reuse() -> None:
    from prism.mcp.server import INSTRUCTIONS

    assert "Reuse PRISM context already in the prompt" in INSTRUCTIONS
    assert "Otherwise call prism_task once" in INSTRUCTIONS
    assert "cover the searched scope only" in INSTRUCTIONS


@pytest.mark.parametrize(
    ("agent", "path"),
    [
        ("codex", "AGENTS.md"),
        ("claude-code", "CLAUDE.md"),
        ("gemini", "GEMINI.md"),
        ("cursor", ".cursor/rules/prism.mdc"),
        ("antigravity", "AGENTS.md"),
    ],
)
@pytest.mark.parametrize("mcp", [False, True])
def test_installed_guidance_uses_selected_transport(
    tmp_path: Path, agent: str, path: str, mcp: bool
) -> None:
    changes = get_integration(agent).plan(tmp_path, IntegrationOptions(mcp=mcp))
    text = next(change.content for change in changes if change.path == path)
    assert text is not None
    assert "do not fetch it again" in text
    assert "Known small edits need no discovery call" in text
    if mcp:
        assert "native MCP tool `prism_task`" in text
        assert 'prism task "' not in text
        assert "do not try an unverified shell fallback" in text
    else:
        assert 'prism task "<user request>"' in text
        assert "native MCP" not in text
