from pathlib import Path

import pytest

from prism.integrations import IntegrationOptions, get_integration


def test_mcp_server_instructions_do_not_override_hook_reuse() -> None:
    from prism.instructions import SHORT
    from prism.mcp.server import INSTRUCTIONS

    assert INSTRUCTIONS == SHORT


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
    from prism.instructions import LOCATED, SHORT

    assert SHORT in text and LOCATED in text
    if mcp:
        assert "native MCP `prism_task`" in text
        assert 'prism task "' not in text
        assert "No unverified shell fallback" in text
    else:
        assert 'prism task "<user request>"' in text
        assert "native MCP" not in text
