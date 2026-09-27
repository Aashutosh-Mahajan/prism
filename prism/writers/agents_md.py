"""The `.aicontext/AGENTS.md` session brief.

PRISM owns the `generated` regions and rewrites them on every scan. The
`narrative` regions belong to the host agent: existing narrative text is
always carried over verbatim.
"""

from __future__ import annotations

from prism.core.markers import RegionKind, parse_regions, render_region
from prism.core.models import Index
from prism.core.tokens import estimate_tokens

BRIEF_TOKEN_LIMIT = 600
TOP_MODULES = 8

NARRATIVE_SECTIONS = ("purpose", "architecture", "conventions")
NARRATIVE_PLACEHOLDER = "_Not written yet. Run the prism-refresh skill to fill this section._"

_SECTION_TITLES = {
    "facts": "Facts",
    "purpose": "Purpose",
    "architecture": "Architecture",
    "conventions": "Conventions",
    "navigation": "Navigation",
}

NAVIGATION = (
    'Before reading files, use `prism search "<words>"` or `prism locate <name>`, then '
    "`prism context <target>` and read only its `read_list`. Run `prism impact <target>` "
    "before changing a public symbol. Check `prism status` if the index may be stale."
)


def _facts(index: Index) -> str:
    lines: list[str] = []
    langs = ", ".join(
        f"{lang} ({n})" for lang, n in sorted(index.languages.items(), key=lambda x: (-x[1], x[0]))
    )
    lines.append(f"- Languages: {langs or 'none detected'}")
    # Tests don't describe the product: their imports and entry points stay out of the brief.
    test_files = set(index.tests_map.test_files)
    ext_counts: dict[str, int] = {}
    for m in index.import_graph.modules.values():
        if m.file not in test_files:
            for name in m.external:
                ext_counts[name] = ext_counts.get(name, 0) + 1
    external = sorted(ext_counts.items(), key=lambda x: (-x[1], x[0]))[:8]
    if external:
        lines.append("- Key dependencies: " + ", ".join(name for name, _ in external))
    eps: list[str] = []
    seen_files: set[str] = set()
    kind_order = {"console_script": 0, "dunder_main": 1, "main_guard": 2, "main_function": 3}
    for ep in sorted(index.entry_points, key=lambda e: (kind_order[e.kind], e.file)):
        if ep.file in seen_files or ep.file in test_files or len(eps) >= 5:
            continue
        seen_files.add(ep.file)
        eps.append(f"`{ep.name or ep.symbol or ep.module}` ({ep.file})")
    if eps:
        lines.append("- Entry points: " + ", ".join(eps))
    if index.commands:
        cmds = ", ".join(f"{k}: `{v}`" for k, v in sorted(index.commands.items()))
        lines.append(f"- Commands: {cmds}")
    mods = sorted(index.import_graph.modules.values(), key=lambda m: (-m.rank, m.id))
    non_test = [m for m in mods if m.file not in test_files][:TOP_MODULES]
    if non_test:
        lines.append("- Top modules by importance: " + ", ".join(f"`{m.id}`" for m in non_test))
    lines.append(
        f"- Size: {len(index.files)} files, {len(index.symbols)} symbols, "
        f"{len(index.tests_map.test_files)} test files"
    )
    return "\n".join(lines)


def render_agents_md(index: Index, existing: str | None = None) -> str:
    previous = parse_regions(existing) if existing else {}

    def section(kind: RegionKind, name: str, generated_body: str | None) -> str:
        if generated_body is None:
            region = previous.get((kind, name))
            body = region.body if region and region.body.strip() else NARRATIVE_PLACEHOLDER
        else:
            body = generated_body
        return f"## {_SECTION_TITLES[name]}\n{render_region(kind, name, body)}"

    parts = [f"# {index.project_name} — Agent Brief", section("generated", "facts", _facts(index))]
    parts.extend(section("narrative", name, None) for name in NARRATIVE_SECTIONS)
    parts.append(section("generated", "navigation", NAVIGATION))
    return "\n\n".join(parts) + "\n"


def brief_tokens(text: str) -> int:
    return estimate_tokens(text)
