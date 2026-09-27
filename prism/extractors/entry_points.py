"""Entry points: `__main__` guards, `__main__.py`, console scripts, `main()` functions."""

from __future__ import annotations

from typing import Any

from prism.core.models import EntryPoint
from prism.extractors.base import Extractor, ExtractorContext
from prism.graph.call_graph import resolve_module_calls


def _script_tables(pyproject: dict[str, Any]) -> dict[str, str]:
    scripts: dict[str, str] = {}
    project = pyproject.get("project", {})
    for table in (project.get("scripts", {}), project.get("gui-scripts", {})):
        if isinstance(table, dict):
            scripts.update({str(k): str(v) for k, v in table.items()})
    poetry = pyproject.get("tool", {}).get("poetry", {}).get("scripts", {})
    if isinstance(poetry, dict):
        scripts.update({str(k): str(v) for k, v in poetry.items() if isinstance(v, str)})
    return scripts


class EntryPointsExtractor(Extractor[list[EntryPoint]]):
    name = "entry_points"

    def run(self, ctx: ExtractorContext) -> list[EntryPoint]:
        table = ctx.table
        found: dict[tuple[str, str, str | None], EntryPoint] = {}

        def add(ep: EntryPoint) -> None:
            found.setdefault((ep.kind, ep.module, ep.name), ep)

        for script, target in sorted(_script_tables(ctx.pyproject).items()):
            mod_part, _, attr = target.partition(":")
            mod = table.modules.find(mod_part.strip())
            if mod is None:
                continue
            attr = attr.split("[")[0].strip()
            sid = f"{mod}.{attr}" if attr else None
            add(
                EntryPoint(
                    kind="console_script",
                    module=mod,
                    file=table.files[mod].path,
                    symbol=sid if sid in table.symbols else None,
                    name=script,
                )
            )

        for mod, pf in sorted(table.files.items()):
            main_sid = f"{mod}.main"
            main_sym = main_sid if main_sid in table.symbols else None
            if pf.has_main_guard:
                called = resolve_module_calls(table, mod, pf.module_calls)
                symbol = main_sym if main_sym in called else (called[0] if called else None)
                add(EntryPoint("main_guard", mod, pf.path, symbol))
            if mod == "__main__" or mod.endswith(".__main__"):
                add(EntryPoint("dunder_main", mod, pf.path, main_sym))
            elif main_sym and not pf.has_main_guard:
                add(EntryPoint("main_function", mod, pf.path, main_sym))
            elif pf.language == "java":
                # `public static void main(String[] args)` inside a class
                for ps in pf.symbols:
                    if (
                        ps.name == "main"
                        and ps.kind == "method"
                        and ps.signature.startswith("static ")
                    ):
                        add(EntryPoint("main_function", mod, pf.path, f"{mod}.{ps.qualname}"))
        return [found[k] for k in sorted(found, key=lambda k: (k[1], k[0], k[2] or ""))]
