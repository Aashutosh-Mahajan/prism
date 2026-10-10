"""CLI, MCP and hook deliver the same packet bytes, and share what a session already received.

The three surfaces call one engine; any difference in what an agent reads is a delivery defect
(different formatting, a different "already sent" memory), not a different capability.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from prism.cli import app
from prism.core.tokens import estimate_tokens
from prism.lifecycle import apply_init, plan_init, scan
from prism.mcp.server import build_server

QUERIES = [
    "where is apply_discount and what calls it",
    "change the free shipping threshold",
    "how does checkout compute the cart total",
    "rename the coupon field",
    "explain the architecture",
    "add logging to create_order",
    "the discount is applied twice with a coupon and a sale",
    "apply_discount",
    "src/shop/pricing/discounts.py",
    "which tests cover the cart",
]


@pytest.fixture
def enabled(small_repo: Path) -> Path:
    apply_init(plan_init(small_repo))
    scan(small_repo)
    return small_repo


def cli_text(root: Path, query: str, *extra: str) -> str:
    result = CliRunner().invoke(app, ["task", query, "--root", str(root), *extra])
    assert result.exit_code == 0, result.output
    return result.output.strip()


def mcp_text(root: Path, query: str, **args: object) -> str:
    server = build_server(root)

    async def call() -> str:
        result = await server.call_tool("prism_task", {"query": query, **args})
        blocks = result[0] if isinstance(result, tuple) else result.content
        return "".join(b.text for b in blocks if hasattr(b, "text")).strip()

    return asyncio.run(call())


@pytest.mark.parametrize("query", QUERIES)
def test_cli_and_mcp_return_identical_text(enabled: Path, query: str) -> None:
    assert mcp_text(enabled, query) == cli_text(enabled, query)


def test_hook_body_matches_cli_for_the_same_budget(enabled: Path) -> None:
    from prism.hooks.prompt import HEADER, user_prompt

    payload = json.dumps(
        {
            "cwd": str(enabled),
            "session_id": "parity",
            "prompt": "where is apply_discount and what calls it",
        }
    )
    out = user_prompt(payload, time_budget=30, inline_build=True)
    assert out.startswith(HEADER)
    body = out[len(HEADER) :].strip()
    match = re.search(r"/(\d+) est\. tokens", body.splitlines()[0])
    assert match is not None
    expected = cli_text(
        enabled,
        "where is apply_discount and what calls it",
        "--budget",
        match[1],
        "--session",
        "independent-cli",
    )
    assert body == expected
    assert estimate_tokens(out) <= 2000


def test_a_repeated_request_is_a_reference_on_every_surface(enabled: Path) -> None:
    query = "where is apply_discount and what calls it"
    first_cli = cli_text(enabled, query, "--session", "s-cli")
    second_cli = cli_text(enabled, "also show apply_discount", "--session", "s-cli")
    assert "[shown earlier in this session]" in second_cli
    assert "```" in first_cli

    first_mcp = mcp_text(enabled, query, session="s-mcp")
    second_mcp = mcp_text(enabled, "also show apply_discount", session="s-mcp")
    assert "[shown earlier in this session]" in second_mcp
    assert "```" in first_mcp


def test_cli_and_mcp_share_session_memory(enabled: Path) -> None:
    """Code sent through one surface is a reference through the other, with the same session id."""
    cli_text(enabled, "where is apply_discount and what calls it", "--session", "shared")
    later = mcp_text(enabled, "also show apply_discount", session="shared")
    assert "[shown earlier in this session]" in later


def test_a_tool_call_shares_the_session_of_the_hook_that_just_answered(enabled: Path) -> None:
    from prism.hooks.prompt import user_prompt

    payload = json.dumps(
        {
            "cwd": str(enabled),
            "session_id": "host-1",
            "prompt": "where is apply_discount and what calls it",
        }
    )
    delivered = user_prompt(payload, time_budget=30, inline_build=True)
    assert delivered
    # The agent now asks the tool for the same code: it must be a reference, not a second copy.
    again = mcp_text(enabled, "also show apply_discount")
    assert "[shown earlier in this session]" in again
    assert cli_text(enabled, "also show apply_discount").count("```") <= again.count("```") + 2


def test_concurrent_hook_sessions_do_not_hide_another_agents_source(enabled: Path) -> None:
    from prism.navigator.session import note_active_session, session_id

    cli_text(enabled, "apply_discount", "--session", "agent-one")
    note_active_session(enabled, "agent-one")
    note_active_session(enabled, "agent-two")
    assert session_id(None, enabled) is None
    assert session_id("agent-one", enabled) == "agent-one"
    assert "```" in mcp_text(enabled, "apply_discount")
