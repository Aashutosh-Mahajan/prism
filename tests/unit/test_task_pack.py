from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from prism.cli import app
from prism.core.errors import UserError
from prism.core.tokens import estimate_tokens
from prism.lifecycle import apply_init, plan_init, scan, update
from prism.mcp.server import PrismTools, enabled_tools
from prism.navigator.api import op_task
from prism.navigator.source_index import search_sources
from prism.navigator.store import IndexStore
from prism.navigator.task_pack import render_task


@pytest.fixture
def indexed(small_repo: Path) -> Path:
    apply_init(plan_init(small_repo))
    scan(small_repo)
    return small_repo


@pytest.mark.parametrize("budget", [128, 256, 512, 2000])
def test_packet_budget_includes_source_and_serialization(indexed: Path, budget: int) -> None:
    with_store = IndexStore.open(indexed)
    try:
        pack = op_task(with_store, "apply_discount", budget)
        assert estimate_tokens(json.dumps(pack, indent=2, ensure_ascii=False)) <= budget
        assert estimate_tokens(render_task(pack)) <= budget
        assert pack["budget"]["used_est"] <= budget
        for block in pack["blocks"]:
            lines = (indexed / block["file"]).read_text().splitlines()
            start, end = block["lines"]
            assert block["source"] == "\n".join(
                f"{i}: {lines[i - 1]}" for i in range(start, end + 1)
            )
    finally:
        with_store.close()


def test_one_call_contains_code_and_graph(indexed: Path) -> None:
    store = IndexStore.open(indexed)
    try:
        pack = op_task(store, "shop.pricing.discounts.apply_discount")
        block = pack["blocks"][0]
        assert block["symbol"] == "shop.pricing.discounts.apply_discount"
        assert "return amount.scale" in block["source"]
        assert not block["truncated"]
        assert any(link["role"] == "caller" for link in pack["links"])
        assert any(link["role"] == "test" for link in pack["links"])
    finally:
        store.close()


def test_body_only_terms_persist_and_warm_queries_skip_source_reads(
    indexed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = indexed / "src/shop/pricing/discounts.py"
    file.write_text(file.read_text() + "\n# coppermoon special case\n")
    update(indexed)
    store = IndexStore.open(indexed)
    try:
        assert search_sources(store, "coppermoon")[0][0] == "src/shop/pricing/discounts.py"
    finally:
        store.close()
    # A new session reuses the persisted postings, without reading any source bodies.
    store = IndexStore.open(indexed)
    monkeypatch.setattr(
        "prism.navigator.source_index.read_indexed_source",
        lambda *args: pytest.fail("warm retrieval reread source"),
    )
    try:
        assert search_sources(store, "coppermoon")[0][0] == "src/shop/pricing/discounts.py"
    finally:
        store.close()


def test_same_length_body_edit_refreshes_only_changed_file(
    indexed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import prism.navigator.source_index as source_index

    file = indexed / "src/shop/pricing/discounts.py"
    file.write_text(file.read_text() + "\n# coppermoon\n")
    update(indexed)
    store = IndexStore.open(indexed)
    search_sources(store, "coppermoon")
    file.write_text(file.read_text().replace("coppermoon", "silvermoon"))
    update(indexed)
    assert not store.is_current()
    store.close()
    store = IndexStore.open(indexed)
    real_read = source_index.read_indexed_source
    reads: list[str] = []

    def read(st: IndexStore, path: str) -> str | None:
        reads.append(path)
        return real_read(st, path)

    monkeypatch.setattr(source_index, "read_indexed_source", read)
    try:
        assert search_sources(store, "silvermoon")[0][0] == "src/shop/pricing/discounts.py"
        assert search_sources(store, "coppermoon") == []
        assert reads == ["src/shop/pricing/discounts.py"]
    finally:
        store.close()


def test_stale_source_not_returned(indexed: Path) -> None:
    store = IndexStore.open(indexed)
    try:
        op_task(store, "apply_discount")
        file = indexed / "src/shop/pricing/discounts.py"
        file.write_text(file.read_text().replace("amount.scale", "amount.changed"))
        pack = op_task(store, "apply_discount")
        assert pack["stale_sources"] > 0
        assert all(b["file"] != "src/shop/pricing/discounts.py" for b in pack["blocks"])
        assert "prism update" in render_task(pack)
    finally:
        store.close()


def test_task_cli_mcp_parity_and_invalid_budget(indexed: Path) -> None:
    tools = PrismTools(indexed)
    try:
        assert "prism_task" in enabled_tools(indexed)
        packet = tools.prism_task("apply_discount", 512)
        cli = CliRunner().invoke(
            app, ["task", "apply_discount", "--root", str(indexed), "--budget", "512", "--json"]
        )
        assert cli.exit_code == 0, cli.output
        assert json.loads(cli.output) == packet
        assert tools.prism_task("apply_discount", 1)["error"] == "user_error"
        with pytest.raises(UserError):
            op_task(tools.store(), "apply_discount", 1000000)
        assert op_task(tools.store(), "", 128)["blocks"] == []
    finally:
        if tools._store:
            tools._store.close()
