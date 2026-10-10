from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from prism.cli import app
from prism.core.tokens import estimate_tokens
from prism.lifecycle import apply_init, plan_init, scan, update
from prism.mcp.server import PrismTools, build_server
from prism.navigator.api import op_knowledge, op_task
from prism.navigator.literals import _quoted_spans
from prism.navigator.request import request_focus
from prism.navigator.session import save_seen
from prism.navigator.store import IndexStore
from prism.navigator.task_pack import render_task


def index(root: Path) -> IndexStore:
    apply_init(plan_init(root))
    scan(root)
    return IndexStore.open(root)


def test_output_shape_backticks_are_context_but_literal_strings_stay() -> None:
    assert _quoted_spans(
        "Extend (value / previous / kind) using `previous` and `change_pct`.", {"previous"}
    ) == ["change_pct"]
    assert _quoted_spans("Replace 'previous' and `previous`.") == ["previous"]
    assert _quoted_spans("Replace 'previous' and `previous`.", {"previous"}) == ["previous"]


def test_shape_extension_does_not_request_global_generic_field_search(tmp_path: Path) -> None:
    (tmp_path / "metrics.py").write_text(
        "def build_metrics(current, previous):\n"
        "    return {'value': current, 'previous': previous, 'kind': 'count'}\n\n"
        + "def unrelated():\n"
        + "    previous = value = 1\n" * 250,
        encoding="utf-8",
    )
    store = index(tmp_path)
    try:
        pack = op_task(
            store,
            "Every metric (value / previous / kind) should include a `delta_pct` field from `value` versus `previous`.",
        )
        assert pack["sufficient"] and not pack.get("search_limited")
        assert "delta_pct" in pack["absent"]
        assert not any(lit["text"] in {"value", "previous"} for lit in pack.get("literals", []))
    finally:
        store.close()


def test_contract_without_callers_does_not_reduce_builder_caller_budget(tmp_path: Path) -> None:
    pytest.importorskip("tree_sitter")
    pytest.importorskip("tree_sitter_typescript")
    (tmp_path / "metrics.py").write_text(
        "def build_metrics(current, previous):\n"
        "    return {'value': current, 'previous': previous, 'kind': 'count'}\n\n"
        + "\n".join(f"def endpoint_{i}():\n    return build_metrics(1, 2)\n" for i in range(5)),
        encoding="utf-8",
    )
    (tmp_path / "contract.ts").write_text(
        "export interface Metric {\n    value: number;\n    previous: number;\n    kind: string;\n}\n",
        encoding="utf-8",
    )
    store = index(tmp_path)
    try:
        pack = op_task(
            store, "Every metric object (value / previous / kind) should include a delta_pct field."
        )
        assert any(block["role"] == "contract" for block in pack["blocks"])
        assert len([link for link in pack["links"] if link["role"] == "caller"]) == 5
        assert not pack.get("callers_omitted")
    finally:
        store.close()


def test_noun_first_request_keeps_operation_but_not_later_constraints() -> None:
    query = "Every metric object (value / previous / kind) should include a delta. Null when no baseline."
    assert request_focus(query) == query.split(". ")[0]
    assert request_focus("How does checkout work? Explain callers.").endswith("Explain callers.")


def test_object_builder_beats_consumers_and_unrelated_tests(tmp_path: Path) -> None:
    (tmp_path / "metrics.py").write_text(
        "def build_metrics(current, previous):\n"
        "    return {'value': current, 'previous': previous, 'kind': 'count'}\n\n"
        "def display_metrics(metric):\n"
        "    return str(metric['value']) + str(metric['previous']) + metric['kind']\n",
        encoding="utf-8",
    )
    (tmp_path / "test_unrelated.py").write_text(
        "def test_values():\n    value = previous = kind = None\n    return value\n",
        encoding="utf-8",
    )
    store = index(tmp_path)
    try:
        pack = op_task(
            store,
            "Every metric object (value / previous / kind) should include a delta. Null when missing previous.",
        )
        assert pack["blocks"][0]["symbol"].endswith(".build_metrics")
        assert pack["sufficient"] and not pack["blocks"][0]["truncated"]
        assert not any(b["file"] == "test_unrelated.py" for b in pack["blocks"])
    finally:
        store.close()


def test_scalar_setting_does_not_require_a_whole_class(tmp_path: Path) -> None:
    (tmp_path / "codes.py").write_text(
        "class VerificationCode:\n    LIFETIME_MINUTES = 10\n"
        + "    padding = 'unrelated'\n" * 150,
        encoding="utf-8",
    )
    store = index(tmp_path)
    try:
        pack = op_task(
            store, "Verification codes should have a lifetime of 15 minutes instead of 10.", 1000
        )
        assert any("LIFETIME_MINUTES = 10" in b.get("source", "") for b in pack["blocks"])
        assert not any("padding" in b.get("source", "") for b in pack["blocks"])
    finally:
        store.close()


def test_literal_frontend_construction_is_included_with_output_shape(tmp_path: Path) -> None:
    (tmp_path / "metrics.py").write_text(
        "def build_metrics(value, previous):\n    return {'value': value, 'previous': previous, 'kind': 'count'}\n",
        encoding="utf-8",
    )
    (tmp_path / "view.tsx").write_text(
        "const snapshot = {value: 2, previous: null, kind: 'count'};\n", encoding="utf-8"
    )
    store = index(tmp_path)
    try:
        packet = op_task(
            store, "Every metric object (value / previous / kind) should include a delta."
        )
        assert any(
            b["file"] == "view.tsx" and "snapshot" in b.get("source", "") for b in packet["blocks"]
        )
    finally:
        store.close()


def test_logging_dictionary_is_not_certified_as_a_returned_shape() -> None:
    from prism.navigator.support import produces_shape

    fields = {"value", "previous", "kind"}
    assert not produces_shape(
        "def log_metric(value):\n    logger.info({'value': value, 'previous': 0, 'kind': 'count'})\n",
        fields,
    )
    assert not produces_shape(
        "def outer():\n    def nested():\n        return {'value': 0, 'previous': 0}\n    return None\n",
        fields,
    )
    assert produces_shape(
        "def builder(value):\n    out = {}\n    out['a'] = {'value': value, 'previous': 0}\n    return out\n",
        fields,
    )


def test_partial_packet_preserves_a_recovery_range_and_delivered_memory(tmp_path: Path) -> None:
    (tmp_path / "large.py").write_text(
        "def important_flow():\n" + "    value = 1234567890\n" * 95 + "    return value\n",
        encoding="utf-8",
    )
    store = index(tmp_path)
    seen: set[tuple[str, int, int]] = set()
    try:
        packet = op_task(store, "important_flow", 500, seen)
        assert not packet["sufficient"] and packet["read_next"]
        assert seen == {(b["file"], *b["lines"]) for b in packet["blocks"] if b.get("source")}
        assert estimate_tokens(json.dumps(packet, indent=2)) <= 500
    finally:
        store.close()


def test_packet_cache_avoids_retrieval_but_invalidates_changed_source(
    small_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = index(small_repo)
    try:
        first = op_task(store, "apply_discount")
        with monkeypatch.context() as patch:
            patch.setattr(
                "prism.navigator.task_pack.build_task",
                lambda *a, **k: pytest.fail("cached request rebuilt"),
            )
            assert op_task(store, "apply_discount") == first
        source = small_repo / "src/shop/pricing/discounts.py"
        source.write_text(source.read_text() + "\n# new body revision\n", encoding="utf-8")
        assert op_task(store, "apply_discount")["stale_sources"] > 0
        update(small_repo)
        store.close()
        store = IndexStore.open(small_repo)
        assert not op_task(store, "apply_discount")["stale_sources"]
    finally:
        store.close()


def test_cached_code_is_hash_verified_even_when_timestamps_are_preserved(small_repo: Path) -> None:
    store = index(small_repo)
    try:
        op_task(store, "apply_discount")
        source = small_repo / "src/shop/pricing/discounts.py"
        before = source.stat()
        text = source.read_text(encoding="utf-8").replace("amount.scale", "amount.other")
        source.write_text(text, encoding="utf-8")
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
        packet = op_task(store, "apply_discount")
        assert packet["stale_sources"] > 0
        assert not any("amount.scale" in b.get("source", "") for b in packet["blocks"])
    finally:
        store.close()


def test_mcp_reconnect_reuses_cli_or_hook_session(small_repo: Path) -> None:
    store = index(small_repo)
    seen: set[tuple[str, int, int]] = set()
    try:
        op_task(store, "apply_discount", 2000, seen)
        save_seen(small_repo, "shared", seen, store.manifest)
    finally:
        store.close()
    tools = PrismTools(small_repo)
    try:
        repeated = tools.prism_task("apply_discount", session="shared")
        assert any(b.get("seen") for b in repeated["blocks"])
        file = small_repo / "src/shop/pricing/discounts.py"
        file.write_text(
            file.read_text().replace("amount.scale", "amount.changed"), encoding="utf-8"
        )
        fresh = tools.prism_task("apply_discount", session="shared")
        assert any("amount.changed" in b.get("source", "") for b in fresh["blocks"])
    finally:
        if tools._store:
            tools._store.close()


def test_native_mcp_compact_text_matches_cli(small_repo: Path) -> None:
    store = index(small_repo)
    try:
        expected = render_task(op_task(store, "apply_discount", 1000))
    finally:
        store.close()
    server = build_server(small_repo)

    async def scenario() -> None:
        result = await server.call_tool("prism_task", {"query": "apply_discount", "budget": 1000})
        content = result[0] if isinstance(result, tuple) else result.content
        assert "\n".join(item.text for item in content if hasattr(item, "text")) == expected
        raw = await server.call_tool(
            "prism_task",
            {"query": "apply_discount", "budget": 1000, "format": "json", "repeat": True},
        )
        structured: Any = (
            raw[1] if isinstance(raw, tuple) else getattr(raw, "structured_content", None)
        )
        if structured is None:
            structured = getattr(raw, "structuredContent", None)
        if structured is None:  # one copy only, as text content
            blocks = raw[0] if isinstance(raw, tuple) else raw.content
            structured = json.loads("".join(b.text for b in blocks if hasattr(b, "text")))
        assert structured["blocks"]

    asyncio.run(scenario())
    cli = CliRunner().invoke(
        app, ["task", "apply_discount", "--root", str(small_repo), "--budget", "1000"]
    )
    assert cli.exit_code == 0 and cli.stdout.strip() == expected.strip()


@pytest.mark.parametrize("budget", [128, 600])
def test_local_knowledge_inspection_is_budgeted(small_repo: Path, budget: int) -> None:
    store = index(small_repo)
    try:
        packet = op_knowledge(store, budget)
        assert packet["counts"]["symbols"] > 0
        assert estimate_tokens(json.dumps(packet, indent=2)) <= budget
        assert "source" not in packet
    finally:
        store.close()
