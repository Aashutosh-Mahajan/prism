from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from prism.cli import app
from prism.core.errors import NotFoundError
from prism.lifecycle import apply_init, plan_init, scan
from prism.mcp.server import PrismTools
from prism.navigator.decision_memory import search_decisions
from prism.navigator.store import IndexStore
from prism.navigator.trace import trace_path
from prism.writers.decisions import add_decision, list_decisions


@pytest.fixture
def indexed(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "main.py").write_text(
        "def leaf():\n    return 42\n\ndef middle():\n    return leaf()\n\ndef entry():\n    return middle()\n",
        encoding="utf-8",
    )
    (root / "other.py").write_text("import main\n", encoding="utf-8")
    apply_init(plan_init(root))
    scan(root)
    return root


def test_directed_path_has_verified_provenance_and_explicit_limits(indexed: Path) -> None:
    store = IndexStore.open(indexed)
    try:
        result = trace_path(store, "main.entry", "main.leaf")
        assert result["found"] and len(result["path"]) == 2
        assert all(edge["provenance"] == "extracted" and edge["line"] for edge in result["path"])
        reverse = trace_path(store, "main.leaf", "main.entry")
        assert not reverse["found"]
        limited = trace_path(store, "main.entry", "main.leaf", depth=1)
        assert not limited["found"] and limited["limited"]
        imports = trace_path(store, "other", "main")
        assert imports["found"] and imports["path"][0]["relation"] == "imports"
    finally:
        store.close()


def test_stale_path_is_not_presented_as_verified(indexed: Path) -> None:
    store = IndexStore.open(indexed)
    (indexed / "main.py").write_text("def unrelated():\n    return 0\n", encoding="utf-8")
    try:
        result = trace_path(store, "main.entry", "main.leaf")
        assert not result["found"] and result["limited"] and result["stale_files"]
    finally:
        store.close()


def test_trace_cli_and_full_mcp_contract(indexed: Path) -> None:
    result = CliRunner().invoke(
        app, ["trace", "main.entry", "main.leaf", "--root", str(indexed), "--json"]
    )
    assert result.exit_code == 0 and '"found": true' in result.output
    assert PrismTools(indexed).prism_trace("main.entry", "main.leaf")["found"]


def test_compact_memory_expands_and_detects_changed_evidence(indexed: Path) -> None:
    record = add_decision(
        indexed,
        "Keep calculation local",
        "Avoid a service roundtrip",
        "Compute the answer in the leaf function.",
        symbols=["main.leaf"],
    )
    result = search_decisions(indexed, "calculation")
    item = result["decisions"][0]
    assert item["validity"] == "current" and "text" not in item
    expanded = search_decisions(indexed, expand_id=record["id"])
    assert "Compute the answer" in expanded["decision"]["text"]
    (indexed / "main.py").write_text("def leaf():\n    return 99\n", encoding="utf-8")
    assert search_decisions(indexed, "calculation")["decisions"][0]["validity"] == "stale"


def test_supersession_filters_search_and_invalid_id_is_atomic(indexed: Path) -> None:
    first = add_decision(
        indexed, "Old calculation design", "Original requirement", "Use old implementation"
    )
    second = add_decision(
        indexed,
        "New calculation design",
        "Changed requirement",
        "Use new implementation",
        supersedes=first["id"],
    )
    assert [d["id"] for d in search_decisions(indexed, "calculation")["decisions"]] == [
        second["id"]
    ]
    before = list_decisions(indexed)
    with pytest.raises(NotFoundError):
        add_decision(
            indexed,
            "Invalid replacement design",
            "Some context",
            "Some decision",
            supersedes="9999",
        )
    assert list_decisions(indexed) == before
