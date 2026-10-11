"""Optional Dart grammar coverage, including complete incremental equivalence."""

import json
import shutil
from pathlib import Path

import pytest

from prism.lifecycle import apply_init, plan_init, scan, update
from prism.parsing.dart_treesitter import DartTreeSitterParser

pytest.importorskip("tree_sitter_dart")
MOBILE = Path(__file__).parents[1] / "fixtures/repos/mobile"


def artifacts(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
        and path.name != "manifest.json"
        and "cache" not in path.relative_to(root).parts
    }


def test_dart_ast_symbols_calls_and_multiline_declaration() -> None:
    parser = DartTreeSitterParser()
    source = b"class Basket {\n  int\n  total(\n    int amount\n  ) {\n    return discount(amount);\n  }\n}\n"
    parsed = parser.parse("basket.dart", source, "basket", False)
    assert not parsed.parse_error
    symbol = next(s for s in parsed.symbols if s.qualname == "Basket.total")
    assert symbol.lines == (2, 7)
    assert [(c.target, c.line) for c in symbol.calls] == [("discount", 6)]


def test_dart_scan_and_updates_equal_full_scan(tmp_path: Path) -> None:
    repo = tmp_path / "work"
    shutil.copytree(MOBILE / "lib", repo / "lib")
    apply_init(plan_init(repo))
    scan(repo)
    graph = json.loads((repo / ".aicontext/call_graph.json").read_text(encoding="utf-8"))
    assert any(
        edge["from"] == "lib.main.main" and edge["to"] == "lib.main.Home" for edge in graph["edges"]
    )
    main = repo / "lib/main.dart"
    for step, (old, new) in enumerate(
        (("describe(p)", "describe(Patient('x', 3))"), ("void main()", "void launch()"))
    ):
        main.write_text(main.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
        update(repo, lazy_rank=False)
        fresh = tmp_path / f"fresh-{step}" / "work"
        shutil.copytree(repo, fresh, ignore=shutil.ignore_patterns(".aicontext", ".gitignore"))
        apply_init(plan_init(fresh))
        scan(fresh, full=True)
        assert artifacts(repo / ".aicontext") == artifacts(fresh / ".aicontext")
