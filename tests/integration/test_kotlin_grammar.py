"""Kotlin optional grammar and complete scan/update artifact equivalence."""

import json
import shutil
from pathlib import Path

import pytest

from prism.lifecycle import apply_init, plan_init, scan, update
from prism.parsing.kotlin_treesitter import KotlinTreeSitterParser

pytest.importorskip("tree_sitter_kotlin")


def artifacts(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file() and p.name != "manifest.json" and "cache" not in p.relative_to(root).parts
    }


def test_kotlin_ast_multiline_methods_and_calls() -> None:
    source = (
        b"class Basket {\n fun total(\n amount: Int\n ): Int {\n return discount(amount)\n }\n}\n"
    )
    parsed = KotlinTreeSitterParser().parse("Basket.kt", source, "Basket", False)
    assert not parsed.parse_error
    symbol = next(s for s in parsed.symbols if s.qualname == "Basket.total")
    assert symbol.lines == (2, 6)
    assert [(c.target, c.line) for c in symbol.calls] == [("discount", 5)]


def test_kotlin_scan_and_updates_equal_full_scan(tmp_path: Path) -> None:
    repo = tmp_path / "work"
    repo.mkdir()
    target = repo / "Basket.kt"
    target.write_text(
        "fun discount(amount: Int): Int { return amount }\nfun total(): Int { return discount(10) }\n",
        encoding="utf-8",
    )
    apply_init(plan_init(repo))
    scan(repo)
    graph = json.loads((repo / ".aicontext/call_graph.json").read_text(encoding="utf-8"))
    assert any(
        e["from"].endswith(".total") and e["to"].endswith(".discount") for e in graph["edges"]
    )
    for step, (old, new) in enumerate(
        (("discount(10)", "discount(20)"), ("total()", "subtotal()"))
    ):
        target.write_text(target.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
        update(repo, lazy_rank=False)
        fresh = tmp_path / f"fresh-{step}" / "work"
        shutil.copytree(repo, fresh, ignore=shutil.ignore_patterns(".aicontext", ".gitignore"))
        apply_init(plan_init(fresh))
        scan(fresh, full=True)
        assert artifacts(repo / ".aicontext") == artifacts(fresh / ".aicontext")
