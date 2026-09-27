"""`.aicontext/modules/<group>.md`: per-module summaries, loaded on demand.

A *group* is a package (its `__init__` plus direct child modules) or a
standalone top-level module. Test modules are left out. Each file has a
PRISM-owned facts region and an agent-owned `summary` narrative region.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from prism.core.markers import parse_regions, render_region
from prism.core.models import Index, Symbol

NARRATIVE_PLACEHOLDER = "_Not written yet. Run the prism-refresh skill to fill this section._"
MAX_API = 12


@dataclass
class ModuleGroup:
    id: str
    modules: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)


def group_of(module: str, is_package: bool, packages: set[str]) -> str:
    if is_package:
        return module
    parent = module.rsplit(".", 1)[0] if "." in module else ""
    return parent if parent in packages else module


def module_groups(index: Index) -> dict[str, ModuleGroup]:
    test_files = set(index.tests_map.test_files)
    nodes = index.import_graph.modules
    packages = {m.id for m in nodes.values() if m.is_package}
    groups: dict[str, ModuleGroup] = {}
    for mid in sorted(nodes):
        node = nodes[mid]
        if node.file in test_files:
            continue
        gid = group_of(mid, node.is_package, packages)
        g = groups.setdefault(gid, ModuleGroup(gid))
        g.modules.append(mid)
        g.files.append(node.file)
    return groups


def group_index(index: Index) -> dict[str, str]:
    """module id -> group id, for every non-test module."""
    return {m: g.id for g in module_groups(index).values() for m in g.modules}


def _api_line(sym: Symbol) -> str:
    doc = f" — {sym.doc}" if sym.doc else ""
    return f"  - `{sym.signature}`{doc} ({sym.file}:{sym.lines[0]})"


def render_facts(index: Index, group: ModuleGroup, groups_of: dict[str, str]) -> str:
    nodes = index.import_graph.modules
    members = set(group.modules)
    lines: list[str] = [f"- Files: {', '.join(group.files)}"]
    doc = next((nodes[m].doc for m in group.modules if nodes[m].doc), "")
    if doc:
        lines.append(f"- Docstring: {doc}")
    public = sorted(
        (
            s
            for s in index.symbols.values()
            if s.module in members and s.visibility == "public" and s.kind != "method"
        ),
        key=lambda s: (-s.rank, s.id),
    )
    if public:
        lines.append("- Public API (by importance):")
        lines.extend(_api_line(s) for s in public[:MAX_API])
        if len(public) > MAX_API:
            lines.append(f"  - … {len(public) - MAX_API} more")
    depends = sorted(
        {
            groups_of[t]
            for m in group.modules
            for t in nodes[m].imports
            if t in groups_of and groups_of[t] != group.id
        }
    )
    used_by = sorted(
        {
            groups_of[s]
            for m in group.modules
            for s in nodes[m].imported_by
            if s in groups_of and groups_of[s] != group.id
        }
    )
    external = sorted({e for m in group.modules for e in nodes[m].external})
    if depends:
        lines.append("- Depends on: " + ", ".join(f"`{d}`" for d in depends))
    if used_by:
        lines.append("- Used by: " + ", ".join(f"`{u}`" for u in used_by))
    if external:
        lines.append("- External: " + ", ".join(external))
    tests = sorted({t for f in group.files for t in index.tests_map.by_file.get(f, [])})
    if tests:
        lines.append("- Tests: " + ", ".join(tests))
    eps = [ep for ep in index.entry_points if ep.module in members]
    if eps:
        lines.append(
            "- Entry points: " + ", ".join(f"`{ep.name or ep.symbol or ep.module}`" for ep in eps)
        )
    return "\n".join(lines)


def render_module_md(
    index: Index, group: ModuleGroup, groups_of: dict[str, str], existing: str | None
) -> str:
    previous = parse_regions(existing) if existing else {}
    region = previous.get(("narrative", "summary"))
    narrative = region.body if region and region.body.strip() else NARRATIVE_PLACEHOLDER
    return (
        f"# Module `{group.id}`\n\n"
        f"{render_region('generated', 'facts', render_facts(index, group, groups_of))}\n\n"
        f"## Summary\n{render_region('narrative', 'summary', narrative)}\n"
    )


def module_filename(group_id: str) -> str:
    return f"{group_id}.md"
