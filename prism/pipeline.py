"""The index pipeline: discovery -> parsing -> symbols -> graphs -> extractors -> health.

`build_index` is shared by `scan` and `update`: an update simply supplies
cached parses for unchanged files and a lazy ranker. Because both run the
same code on the same inputs, a scan and scan+updates produce the same index.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from prism.config import PrismConfig, load_config
from prism.core.models import GitIntel, Index, ParsedFile, SourceFile
from prism.core.paths import AICONTEXT
from prism.discovery import discover
from prism.extractors import (
    EntryPointsExtractor,
    ExtractorContext,
    ProjectExtractor,
    TestsMapExtractor,
)
from prism.extractors.blast_radius import BlastRadiusExtractor
from prism.extractors.config_keys import ConfigExtractor
from prism.extractors.dead_code import DeadCodeExtractor
from prism.extractors.models import ModelsExtractor
from prism.extractors.routes import RoutesExtractor
from prism.graph import build_call_graph, build_import_graph, build_symbol_table
from prism.graph.communities import louvain
from prism.graph.ranking import Ranker, pagerank
from prism.health import collect_git, compute_health, read_coverage
from prism.parsing import get_parser, module_name

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


def _load_pyproject(root: Path) -> dict[str, Any]:
    path = root / "pyproject.toml"
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def parse_files(
    root: Path,
    files: list[SourceFile],
    config: PrismConfig,
    cached: dict[str, ParsedFile] | None = None,
) -> tuple[list[ParsedFile], int]:
    """Parse files, reusing `cached` entries. Returns (parsed, number actually parsed)."""
    cached = cached or {}
    parsed: list[ParsedFile] = []
    fresh = 0
    for f in files:
        parser = get_parser(f.language)
        if parser is None:
            continue
        mod, is_pkg = module_name(f.path, config.source_roots, f.language)
        hit = cached.get(f.path)
        if hit is not None and hit.module == mod:
            parsed.append(hit)
            continue
        fresh += 1
        try:
            source = (root / f.path).read_bytes()
        except OSError as exc:
            pf = ParsedFile(f.path, f.language, mod, is_pkg, 0, "")
            pf.parse_error = f"OSError: {exc}"
            parsed.append(pf)
            continue
        parsed.append(parser.parse(f.path, source, mod, is_pkg))
    return parsed, fresh


def open_finding_counts(root: Path) -> dict[str, int]:
    """Open audit findings per file and per symbol (feeds risk)."""
    path = root / AICONTEXT / "audit" / "findings.json"
    counts: dict[str, int] = {}
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError):
        return counts
    for f in data.get("findings", []):
        if f.get("status") != "open":
            continue
        for key in (f.get("file"), f.get("symbol")):
            if key:
                counts[key] = counts.get(key, 0) + 1
    return counts


def build_index(
    root: Path,
    config: PrismConfig | None = None,
    known_files: dict[str, Any] | None = None,
    *,
    cached: dict[str, ParsedFile] | None = None,
    call_ranker: Ranker = pagerank,
    import_ranker: Ranker = pagerank,
    previous_git: GitIntel | None = None,
    files: list[SourceFile] | None = None,
) -> Index:
    root = root.resolve()
    config = config or load_config(root)
    if files is None:
        files = discover(root, config, known_files)
    parsed, _ = parse_files(root, files, config, cached)
    table = build_symbol_table(parsed)
    import_graph = build_import_graph(table, import_ranker)
    call_graph = build_call_graph(table, call_ranker)
    pyproject = _load_pyproject(root)
    ctx = ExtractorContext(
        root=root,
        config=config,
        table=table,
        import_graph=import_graph,
        call_graph=call_graph,
        pyproject=pyproject,
    )
    entry_points = EntryPointsExtractor().run(ctx)
    for ep in entry_points:
        node = import_graph.modules.get(ep.module)
        if node is not None and node.entry_point is None:
            node.entry_point = ep.kind
    tests_map = TestsMapExtractor().run(ctx)
    # Communities over imports plus (aggregated) calls, excluding tests so they don't glue areas together.
    test_set = set(tests_map.test_files)
    module_of = {sid: sym.module for sid, sym in table.symbols.items()}
    comm_edges = [(e.source, e.target, 1.0) for e in import_graph.edges]
    comm_edges += [(module_of[e.source], module_of[e.target], 0.5) for e in call_graph.edges]
    members = [m.id for m in import_graph.modules.values() if m.file not in test_set]
    for mid, c in louvain(members, comm_edges).items():
        import_graph.modules[mid].community = c
    for node in import_graph.modules.values():
        if node.file in test_set:
            node.community = -1
    project = ProjectExtractor().run(ctx)
    routes = RoutesExtractor().run(ctx)
    models = ModelsExtractor().run(ctx)
    config_keys = ConfigExtractor().run(ctx)
    dead_code = DeadCodeExtractor(entry_points).run(ctx)
    blast = BlastRadiusExtractor().run(ctx)

    indexed = {f.path for f in files}
    git = collect_git(root, indexed, previous_git)
    complexity = {
        f"{pf.module}.{ps.qualname}": ps.complexity
        for pf in table.files.values()
        for ps in pf.symbols
    }
    test_files = set(tests_map.test_files)
    health = compute_health(
        parsed=table.files.values(),
        symbols=table.symbols,
        complexity=complexity,
        module_rank={m.id: m.rank for m in import_graph.modules.values()},
        tested_files=set(tests_map.by_file),
        tested_symbols=set(tests_map.by_symbol),
        git=git,
        coverage=read_coverage(root, indexed),
        open_findings=open_finding_counts(root),
        test_files=test_files,
    )

    languages: dict[str, int] = {}
    for f in files:
        languages[f.language] = languages.get(f.language, 0) + 1
    return Index(
        root=root.as_posix(),
        files=files,
        parsed=parsed,
        symbols=table.symbols,
        import_graph=import_graph,
        call_graph=call_graph,
        entry_points=entry_points,
        tests_map=tests_map,
        languages=languages,
        project_name=project.name,
        commands=project.commands,
        declared_dependencies=project.dependencies,
        routes=routes,
        models=models,
        config=config_keys,
        dead_code=dead_code,
        blast=blast,
        git=git,
        health=health,
    )
