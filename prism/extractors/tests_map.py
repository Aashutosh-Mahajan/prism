"""Test <-> code mapping from test calls, test imports, HTTP requests to routes, and file naming."""

from __future__ import annotations

import re
from collections.abc import Sequence

from prism.core.models import Route, TestsMap
from prism.extractors.base import Extractor, ExtractorContext
from prism.graph.call_graph import resolve_module_calls

_JS_TEST_MARKERS = (".test.", ".spec.")
# `self.client.post("/api/...")`, `request(app).get('/x')`, `fetch("/x")`: the URL a test drives.
_HTTP_CALL = re.compile(
    r"""(?:\.(get|post|put|patch|delete|head|options)|\bfetch)\(\s*[frbu]?["'`](/[^"'`\s?#{$]*)""",
    re.IGNORECASE,
)
# Django `reverse("send-otp")` / `reverse_lazy('app:detail')`: the URL name a test requests.
_REVERSE = re.compile(r"""\breverse(?:_lazy)?\(\s*["']([\w:.-]+)["']""")
_PARAMETER = re.compile(r"^(?:<[^>]+>|\{[^}]+\}|:\w+|\(\?P<\w+>.*\)|\[\w+\])$")
MAX_TEST_SOURCE = 1_000_000  # characters; a larger "test" file is data, not tests
MAX_ROUTE_TIES = 3


def _segments(path: str) -> list[str]:
    return [part for part in path.strip("/").split("/") if part]


def _route_score(request: list[str], route: list[str]) -> int:
    """Literal segments matched when `route` is a suffix of the requested path, else 0.

    Route paths are recorded without the prefixes they are mounted under (`include()`,
    routers), so `/api/v1/auth/login/` must match the route `/auth/login/`."""
    if not route or len(route) > len(request):
        return 0
    literals = 0
    for asked, part in zip(request[-len(route) :], route, strict=True):
        if _PARAMETER.match(part):
            continue
        if asked.lower() != part.lower():
            return 0
        literals += 1
    return literals


def routes_requested(source: str, routes: Sequence[Route]) -> set[str]:
    """Handler ids of the routes a test file's HTTP calls request (best match per call)."""
    handlers: set[str] = set()
    shapes = [(_segments(r.path), r) for r in routes]
    for match in _HTTP_CALL.finditer(source[:MAX_TEST_SOURCE]):
        verb = (match[1] or "get").upper()
        request = _segments(match[2])
        if not request:
            continue
        scored = [
            (score, route)
            for shape, route in shapes
            if route.method in ("ANY", verb) and (score := _route_score(request, shape))
        ]
        if not scored:
            continue
        best = max(score for score, _ in scored)
        tied = {route.handler for score, route in scored if score == best}
        if len(tied) <= MAX_ROUTE_TIES:
            handlers |= tied
    return handlers


def url_names_requested(source: str, names: dict[str, set[str]]) -> set[str]:
    """Handler ids of the named Django URLs a test file passes to `reverse()`."""
    handlers: set[str] = set()
    for match in _REVERSE.finditer(source[:MAX_TEST_SOURCE]):
        found = names.get(match[1].rsplit(":", 1)[-1], set())  # drop an `app:` namespace
        if 0 < len(found) <= MAX_ROUTE_TIES:
            handlers |= found
    return handlers


def _url_names(ctx: ExtractorContext) -> dict[str, set[str]]:
    from prism.graph.call_graph import Resolver

    names: dict[str, set[str]] = {}
    resolver: Resolver | None = None
    for mod, pf in ctx.table.files.items():
        for up in pf.url_patterns:
            if not up.name:
                continue
            resolver = resolver or Resolver(ctx.table)
            handler = resolver.resolve_name(mod, up.view)
            if handler is not None:
                names.setdefault(up.name, set()).add(handler)
    return names


def _shared_prefix(a: str, b: str) -> int:
    count = 0
    for x, y in zip(a.split("/")[:-1], b.split("/")[:-1], strict=False):
        if x != y:
            break
        count += 1
    return count


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
    if name in ("tests.py", "test.py"):  # Django's per-app convention
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

    def __init__(self, routes: Sequence[Route] = ()) -> None:
        self.routes = list(routes)

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

        # Tests that drive the app through its HTTP API never call the view: the URL links them.
        names = _url_names(ctx)
        if self.routes or names:
            for test in test_files:
                try:
                    source = (ctx.root / test).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                requested = routes_requested(source, self.routes) if self.routes else set()
                for handler in requested | url_names_requested(source, names):
                    sym = table.symbols.get(handler)
                    if sym is not None and sym.file not in test_set:
                        by_symbol.setdefault(handler, set()).add(test)
                        by_file.setdefault(sym.file, set()).add(test)

        stems: dict[str, list[str]] = {}
        for pf in table.files.values():
            if pf.path not in test_set:
                stems.setdefault(pf.path.rsplit("/", 1)[-1].rsplit(".", 1)[0], []).append(pf.path)
        for test in test_files:
            subject = _subject_stem(test)
            candidates = stems.get(subject or "", [])
            if len(candidates) > 1:
                # `medical/tests/test_views.py` is about `medical/views.py`, not every views.py.
                nearest = max(_shared_prefix(test, path) for path in candidates)
                if nearest:
                    candidates = [p for p in candidates if _shared_prefix(test, p) == nearest]
            for path in candidates:
                by_file.setdefault(path, set()).add(test)

        return TestsMap(
            test_files=test_files,
            by_symbol={k: sorted(v) for k, v in sorted(by_symbol.items())},
            by_file={k: sorted(v) for k, v in sorted(by_file.items())},
        )
