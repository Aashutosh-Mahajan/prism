"""Behavioral contracts for compact maps, self-contained code and honest limits."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prism.core.errors import UserError
from prism.core.tokens import estimate_tokens
from prism.lifecycle import apply_init, plan_init, scan
from prism.navigator.api import op_task
from prism.navigator.fusion import fuse_files
from prism.navigator.literals import find_literals
from prism.navigator.source_index import SourceIndex, SourceReader
from prism.navigator.store import IndexStore
from prism.navigator.task_pack import render_task


def index(repo: Path) -> IndexStore:
    apply_init(plan_init(repo))
    scan(repo)
    return IndexStore.open(repo)


def test_retrieval_agreement_wins_without_duplicate_symbol_votes() -> None:
    fused = fuse_files(
        [["body_only.py", "shared.py"], ["symbols_only.py", "shared.py", "shared.py"]], 3
    )
    assert fused[0][0] == "shared.py"
    assert len(fused) == 3
    assert fused == fuse_files([["body_only.py", "shared.py"], ["symbols_only.py", "shared.py"]], 3)


@pytest.mark.parametrize("budget", [128, 256, 512, 1200, 2000])
def test_architecture_is_a_budgeted_map_not_source_dump(small_repo: Path, budget: int) -> None:
    with_store = index(small_repo)
    try:
        pack = op_task(with_store, "understand the repository architecture", budget)
        assert pack["intent"] == "overview"
        assert not pack["blocks"] and not pack["sufficient"]
        assert estimate_tokens(render_task(pack)) <= budget
        assert estimate_tokens(json.dumps(pack, indent=2, ensure_ascii=False)) <= budget
        if budget >= 1200:
            assert pack["overview"]["files"]
            assert any(row["symbols"] for row in pack["overview"]["files"])
            assert "Map:" in render_task(pack)
    finally:
        with_store.close()


def test_file_overview_and_explicit_code_mode(small_repo: Path) -> None:
    store = index(small_repo)
    try:
        overview = op_task(store, "src/shop/pricing/discounts.py", mode="overview")
        assert overview["overview"]["files"][0]["file"] == "src/shop/pricing/discounts.py"
        assert "apply_discount" in render_task(overview)
        assert not overview["blocks"]
        code = op_task(store, "apply_discount", mode="code")
        assert code["blocks"] and "return amount.scale" in code["blocks"][0]["source"]
        scoped = op_task(store, "src/shop/pricing/discounts.py::apply_discount")
        assert scoped["blocks"][0]["symbol"].endswith(".apply_discount")
        line = op_task(store, "src/shop/pricing/discounts.py:10")
        assert line["blocks"][0]["symbol"].endswith(".apply_discount")
        excerpt = op_task(store, "src/shop/pricing/discounts.py:10-12")
        assert excerpt["blocks"][0]["lines"] == [10, 12]
        assert not excerpt["blocks"][0]["truncated"]
        with pytest.raises(UserError):
            op_task(store, "src/shop/pricing/discounts.py:12-10")
        with pytest.raises(UserError):
            op_task(store, "apply_discount", mode="invalid")
    finally:
        store.close()


def test_cooperating_methods_include_their_shared_constant(tmp_path: Path) -> None:
    (tmp_path / "privacy.py").write_text(
        "PATTERNS = {'secret': 'needle'}\n"
        "UNRELATED = 'do not include me'\n\n"
        "class Privacy:\n"
        "    def detect_sensitive(self, text):\n"
        "        return PATTERNS['secret'] in text\n\n"
        "    def mask_sensitive(self, text):\n"
        "        return text.replace(PATTERNS['secret'], '[MASKED]')\n",
        encoding="utf-8",
    )
    store = index(tmp_path)
    try:
        pack = op_task(store, "fix privacy sensitive detection and masking", 2000)
        source = "\n".join(block.get("source", "") for block in pack["blocks"])
        assert "def detect_sensitive" in source and "def mask_sensitive" in source
        assert "PATTERNS =" in source
        assert "UNRELATED =" not in source
        assert estimate_tokens(render_task(pack)) <= 2000
    finally:
        store.close()


def test_small_packet_does_not_hide_undelivered_lines(tmp_path: Path) -> None:
    file = tmp_path / "service.py"
    file.write_text(
        "def important_flow():\n" + "    value = 1234567890\n" * 95 + "    return value\n"
    )
    store = index(tmp_path)
    seen: set[tuple[str, int, int]] = set()
    try:
        first = op_task(store, "important_flow", 400, seen)
        assert first["blocks"] and first["blocks"][0]["truncated"]
        assert not first["sufficient"]
        delivered = {line for _, start, end in seen for line in range(start, end + 1)}
        assert len(delivered) < 97
        second = op_task(store, "important_flow", 4000, seen)
        added = {
            line
            for block in second["blocks"]
            if "source" in block
            for line in range(block["lines"][0], block["lines"][1] + 1)
        }
        assert added and not added & delivered
        assert 97 in added
        assert estimate_tokens(json.dumps(second, indent=2, ensure_ascii=False)) <= 4000
    finally:
        store.close()


@pytest.mark.parametrize("budget", [128, 256, 2000])
def test_capped_match_search_never_claims_exhaustive_or_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, budget: int
) -> None:
    for n in range(3):
        (tmp_path / f"f{n}.py").write_text(f"CAP_PROBE = {n}\n")
    store = index(tmp_path)
    monkeypatch.setattr("prism.navigator.literals.MAX_FILES_PER_LITERAL", 2)
    try:
        with SourceIndex(store) as sources:
            evidence = find_literals(sources, SourceReader(store), "CAP_PROBE")
        assert evidence.limited and not evidence.absent
        assert evidence.literals and not evidence.literals[0].complete
        pack = op_task(store, "CAP_PROBE", budget)
        assert pack["search_limited"] and not pack["sufficient"]
        assert "repository-wide coverage" in render_task(pack)
        assert all(not literal["complete"] for literal in pack.get("literals", []))
        assert estimate_tokens(render_task(pack)) <= budget
        assert estimate_tokens(json.dumps(pack, indent=2, ensure_ascii=False)) <= budget
    finally:
        store.close()


def test_long_matching_line_is_not_silently_skipped(tmp_path: Path) -> None:
    file = tmp_path / "long.py"
    file.write_text("# " + "padding " * 90 + "LONG_MARKER\n")
    store = index(tmp_path)
    try:
        with SourceIndex(store) as sources:
            evidence = find_literals(sources, SourceReader(store), "LONG_MARKER")
        assert evidence.literals and evidence.literals[0].complete
        assert evidence.literals[0].total == 1
    finally:
        store.close()
