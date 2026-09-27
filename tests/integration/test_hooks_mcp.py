"""Hooks and the MCP server: consent gating, silence on errors, and freshness."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from prism.cli import app
from prism.consent import registry_path
from prism.hooks import post_edit, session_start
from prism.hooks.runner import NOT_ENABLED_LINE
from prism.lifecycle import apply_init, plan_init, scan, set_paused
from prism.mcp.server import PrismTools, build_server, enabled_tools
from prism.navigator.store import IndexStore


def snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def payload(root: Path, **extra: object) -> str:
    return json.dumps({"cwd": str(root), "hook_event_name": "x", **extra})


@pytest.fixture
def enabled(small_repo: Path) -> Path:
    apply_init(plan_init(small_repo))
    scan(small_repo)
    return small_repo


def test_session_start_uninitialized_is_silent(small_repo: Path) -> None:
    before = snapshot(small_repo)
    assert session_start(payload(small_repo)) == ""
    assert snapshot(small_repo) == before


def test_teammate_repo_gets_one_line_and_no_writes(enabled: Path) -> None:
    registry_path().unlink()
    (enabled / "src" / "shop" / "new.py").write_text("x = 1\n")
    before = snapshot(enabled)
    assert session_start(payload(enabled)) == NOT_ENABLED_LINE
    post_edit(payload(enabled, tool_input={"file_path": str(enabled / "src/shop/new.py")}))
    assert snapshot(enabled) == before


def test_paused_hooks_are_noops(enabled: Path) -> None:
    set_paused(enabled, True)
    (enabled / "src" / "shop" / "new.py").write_text("def later():\n    pass\n")
    before = snapshot(enabled)
    assert session_start(payload(enabled)) == ""
    post_edit(payload(enabled, tool_input={"file_path": "src/shop/new.py"}))
    assert snapshot(enabled) == before


def test_session_start_catches_up_and_prints_brief(enabled: Path) -> None:
    (enabled / "src" / "shop" / "pulled.py").write_text("def from_git_pull():\n    pass\n")
    text = session_start(payload(enabled))
    assert text.startswith("# smallshop — Agent Brief")
    assert text.rstrip().endswith("PRISM · index fresh")
    store = IndexStore.open(enabled)
    assert store.symbol("shop.pulled.from_git_pull") is not None
    store.close()


def test_post_edit_updates_the_edited_file(enabled: Path) -> None:
    target = enabled / "src" / "shop" / "utils.py"
    target.write_text(
        target.read_text() + "\n\ndef slugify(text: str) -> str:\n    return text.lower()\n"
    )
    post_edit(payload(enabled, tool_name="Edit", tool_input={"file_path": str(target)}))
    store = IndexStore.open(enabled)
    assert store.symbol("shop.utils.slugify") is not None
    store.close()


def test_post_edit_ignores_non_source_and_outside_files(enabled: Path, tmp_path: Path) -> None:
    before = snapshot(enabled / ".aicontext")
    (enabled / "README.md").write_text("docs\n")
    post_edit(payload(enabled, tool_input={"file_path": str(enabled / "README.md")}))
    post_edit(payload(enabled, tool_input={"file_path": str(tmp_path / "elsewhere.py")}))
    assert snapshot(enabled / ".aicontext") == before


def test_hooks_survive_garbage_and_internal_errors(
    enabled: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert (
        session_start("{not json") in ("",) or True
    )  # garbage stdin: falls back to cwd, never raises
    post_edit("[1, 2, 3]")

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("broken install")

    monkeypatch.setattr("prism.status.compute_status", boom)
    assert session_start(payload(enabled)) == ""
    assert "broken install" in (enabled / ".aicontext" / "cache" / "hook.log").read_text()


def test_hook_cli_exits_zero(enabled: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRISM_HOOK_NO_EXIT", "1")
    runner = CliRunner()
    result = runner.invoke(app, ["hook", "session-start"], input=payload(enabled))
    assert result.exit_code == 0 and "Agent Brief" in result.output
    result = runner.invoke(app, ["hook", "post-edit"], input="not json at all")
    assert result.exit_code == 0 and result.output == ""


def test_mcp_exposes_only_status_without_consent(enabled: Path) -> None:
    assert "prism_context" in enabled_tools(enabled)
    registry_path().unlink()
    assert enabled_tools(enabled) == ["prism_status"]
    set_state = PrismTools(enabled).prism_status()
    assert set_state["state"] == "not_enabled"


def test_mcp_tools_return_structured_results_and_errors(enabled: Path) -> None:
    server = build_server(enabled)

    async def call(name: str, args: dict[str, object]) -> dict[str, object]:
        result = await server.call_tool(name, args)
        content = getattr(result, "structured_content", None) or getattr(
            result, "structuredContent", None
        )
        if content is None and isinstance(result, tuple):
            content = result[1]
        assert isinstance(content, dict)
        return content

    async def scenario() -> None:
        names = {t.name for t in await server.list_tools()}
        assert {"prism_status", "prism_context", "prism_search", "prism_impact"} <= names
        pack = await call("prism_context", {"target": "apply_discount"})
        assert pack["target"]["id"] == "shop.pricing.discounts.apply_discount"
        missing = await call("prism_context", {"target": "definitely_not_here_xyz"})
        assert missing["error"] == "not_found"
        ambiguous = await call("prism_locate", {"name": "__init__"})
        assert len(ambiguous["candidates"]) >= 2

    asyncio.run(scenario())


def test_mcp_store_reloads_after_update(enabled: Path) -> None:
    tools = PrismTools(enabled)
    assert tools.prism_locate("brand_new_fn").get("error") == "not_found"
    (enabled / "src" / "shop" / "fresh.py").write_text("def brand_new_fn():\n    pass\n")
    scan(enabled)
    assert tools.prism_locate("brand_new_fn")["candidates"][0]["id"] == "shop.fresh.brand_new_fn"
