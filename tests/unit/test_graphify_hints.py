"""Optional imported relationships must stay advisory, local and source-verified."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prism.lifecycle import apply_init, plan_init, scan
from prism.navigator.api import op_task
from prism.navigator.graphify import GraphifyGraph
from prism.navigator.source_index import SourceReader
from prism.navigator.store import IndexStore


def exported(repo: Path, confidence: str, outside: bool = False) -> Path:
    graph = repo / "graph.json"
    graph.write_text(
        json.dumps(
            {
                "directed": False,
                "nodes": [
                    {"id": "doc", "label": "coppermoon behavior", "source_file": ""},
                    {
                        "id": "code",
                        "label": "apply_discount",
                        "source_file": "../outside.py"
                        if outside
                        else "src/shop/pricing/discounts.py",
                        "source_location": "L999",
                    },
                ],
                "edges": [
                    {
                        "source": "code",
                        "target": "doc",
                        "_src": "doc",
                        "_tgt": "code",
                        "relation": "documents",
                        "confidence": confidence,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return graph


@pytest.mark.parametrize("confidence", ["EXTRACTED", "INFERRED"])
def test_document_link_resolves_current_symbol_not_old_line(
    small_repo: Path, confidence: str
) -> None:
    apply_init(plan_init(small_repo))
    scan(small_repo)
    file = exported(small_repo, confidence)
    (small_repo / "prism.toml").write_text('graphify_graph = "graph.json"\n')
    store = IndexStore.open(small_repo)
    try:
        hints = GraphifyGraph.load(file, small_repo).hints(store, SourceReader(store), "coppermoon")
        assert hints and hints[0].start != 999
        assert hints[0].symbol and hints[0].symbol.name == "apply_discount"
        pack = op_task(store, "coppermoon")
        assert pack["blocks"][0]["role"] == "graphify hint"
        assert pack["confidence"] == "medium" and not pack["sufficient"]
        target = small_repo / "src/shop/pricing/discounts.py"
        target.write_text(target.read_text().replace("amount.scale", "amount.changed"))
        assert not GraphifyGraph.load(file, small_repo).hints(
            store, SourceReader(store), "coppermoon"
        )
    finally:
        store.close()


@pytest.mark.parametrize("confidence,outside", [("AMBIGUOUS", False), ("EXTRACTED", True)])
def test_uncertain_edges_and_outside_sources_are_not_hints(
    small_repo: Path, confidence: str, outside: bool
) -> None:
    apply_init(plan_init(small_repo))
    scan(small_repo)
    file = exported(small_repo, confidence, outside)
    store = IndexStore.open(small_repo)
    try:
        assert not GraphifyGraph.load(file, small_repo).hints(
            store, SourceReader(store), "coppermoon"
        )
    finally:
        store.close()
