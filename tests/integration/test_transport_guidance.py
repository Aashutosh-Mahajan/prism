from pathlib import Path

import pytest

from prism.integrations import IntegrationOptions, get_integration


def test_mcp_server_instructions_do_not_override_hook_reuse() -> None:
    from prism.instructions import SHORT
    from prism.mcp.server import INSTRUCTIONS

    # Reuse stays the first rule: MCP replaces grep and reads only for code not yet delivered.
    assert INSTRUCTIONS.startswith(SHORT) and "you don't have yet" in INSTRUCTIONS


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
    from prism.instructions import LOCATED, RECOVERY, SHORT

    assert SHORT in text and LOCATED in text
    assert RECOVERY in text  # transport failure must allow bounded ordinary investigation
    if mcp:
        assert "MCP `prism_task` for code you lack" in text
        assert 'prism task "' not in text
    else:
        assert 'prism task "<user request>"' in text
        assert "MCP `prism_task`" not in text
