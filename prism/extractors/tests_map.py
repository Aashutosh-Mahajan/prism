"""Test <-> code mapping from test calls, test imports, and file naming."""

from __future__ import annotations

from collections.abc import Sequence

from prism.core.models import TestsMap
from prism.extractors.base import Extractor, ExtractorContext
from prism.graph.call_graph import resolve_module_calls

_JS_TEST_MARKERS = (".test.", ".spec.")


def is_test_file(path: str, test_dirs: Sequence[str]) -> bool:
    """Python (test_*.py, *_test.py, conftest.py), JS/TS (*.test.ts, *.spec.js, __tests__/),
    Go (*_test.go), Java (*Test.java, src/test/), or anything under a configured test dir."""
    parts = path.split("/")
    name = parts[-1]
    if name == "conftest.py" or "__tests__" in parts:
        return True
    if any(m in name for m in _JS_TEST_MARKERS):
        return True
    stem = name.rsplit(".", 1)[0]
    if stem.startswith("test_") or stem.endswith("_test"):
        return True
    if name.endswith(".java") and (
        stem.endswith(("Test", "Tests", "IT")) or "/src/test/" in f"/{path}"
    ):
        return True
    return any(p in test_dirs for p in parts[:-1])


def _subject_stem(test_path: str) -> str | None:
    name = test_path.rsplit("/", 1)[-1]
    for marker in _JS_TEST_MARKERS:
        if marker in name:
            return name.split(marker)[0]
    stem = name.rsplit(".", 1)[0]
    if stem.startswith("test_"):
        return stem[5:]
    if stem.endswith("_test"):
        return stem[:-5]
    if name.endswith(".java"):
        for suffix in ("Tests", "Test", "IT"):
            if stem.endswith(suffix):
                return stem[: -len(suffix)]
    return None


class TestsMapExtractor(Extractor[TestsMap]):
    name = "tests_map"

    def run(self, ctx: ExtractorContext) -> TestsMap:
        table = ctx.table
        test_dirs = ctx.config.test_dirs
        test_files = sorted(
            pf.path for pf in table.files.values() if is_test_file(pf.path, test_dirs)
        )
        test_set = set(test_files)
        by_symbol: dict[str, set[str]] = {}
        by_file: dict[str, set[str]] = {}

        for edge in ctx.call_graph.edges:
            src = table.symbols[edge.source]
            dst = table.symbols[edge.target]
            if src.file in test_set and dst.file not in test_set:
                by_symbol.setdefault(dst.id, set()).add(src.file)
                by_file.setdefault(dst.file, set()).add(src.file)

        # Tests written as module-level callbacks (Jest/Vitest `test(() => ...)`, pytest-bdd, ...)
        for mod, pf in sorted(table.files.items()):
            if pf.path not in test_set or not pf.module_calls:
                continue
            for target in resolve_module_calls(table, mod, pf.module_calls):
                dst = table.symbols[target]
                if dst.file not in test_set:
                    by_symbol.setdefault(dst.id, set()).add(pf.path)
                    by_file.setdefault(dst.file, set()).add(pf.path)

        for e in ctx.import_graph.edges:
            src_file = ctx.import_graph.modules[e.source].file
            dst_file = ctx.import_graph.modules[e.target].file
            if src_file in test_set and dst_file not in test_set:
                by_file.setdefault(dst_file, set()).add(src_file)

        stems: dict[str, list[str]] = {}
        for pf in table.files.values():
            if pf.path not in test_set:
                stems.setdefault(pf.path.rsplit("/", 1)[-1].rsplit(".", 1)[0], []).append(pf.path)
        for test in test_files:
            subject = _subject_stem(test)
            for path in stems.get(subject or "", []):
                by_file.setdefault(path, set()).add(test)

        return TestsMap(
            test_files=test_files,
            by_symbol={k: sorted(v) for k, v in sorted(by_symbol.items())},
            by_file={k: sorted(v) for k, v in sorted(by_file.items())},
        )
