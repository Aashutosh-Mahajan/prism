"""Dead-code candidates: symbols nothing calls, references, imports, or registers.

These are candidates only. Dynamic use (getattr, plugin registries, framework
conventions, public library API) is invisible to static analysis, so public
symbols are reported with `possible` confidence and the audit skill must
check before recording anything.
"""

from __future__ import annotations

from prism.core.models import DeadCode, EntryPoint
from prism.extractors.base import Extractor, ExtractorContext
from prism.extractors.tests_map import is_test_file

_NEUTRAL_DECORATORS = frozenset(
    {"staticmethod", "classmethod", "abstractmethod", "abc.abstractmethod"}
)


class DeadCodeExtractor(Extractor[list[DeadCode]]):
    name = "dead_code"

    def __init__(self, entry_points: list[EntryPoint] | None = None) -> None:
        self.entry_points = entry_points or []

    def run(self, ctx: ExtractorContext) -> list[DeadCode]:
        table = ctx.table
        test_dirs = ctx.config.test_dirs
        referenced: set[str] = set()
        exported: set[str] = set()
        for mod, pf in table.files.items():
            referenced.update(pf.names_used)
            for name in pf.all_names or []:
                exported.add(f"{mod}.{name}")
        imported_targets: set[str] = set()
        for scope in table.scopes.values():
            for target in scope.bindings.values():
                imported_targets.add(target.rsplit(".", 1)[-1])
        entry_symbols = {ep.symbol for ep in self.entry_points if ep.symbol}
        method_names: dict[str, int] = {}
        for sym in table.symbols.values():
            if sym.kind == "method":
                method_names[sym.name] = method_names.get(sym.name, 0) + 1
        subclassed: set[str] = set()
        for pf in table.files.values():
            for ps in pf.symbols:
                subclassed.update(b.rsplit(".", 1)[-1] for b in ps.bases)

        out: list[DeadCode] = []
        for sid, sym in sorted(table.symbols.items()):
            if sym.called_by or sid in entry_symbols or sid in exported:
                continue
            if is_test_file(sym.file, test_dirs) or sym.name.startswith("__"):
                continue
            if any(d.split("(")[0] not in _NEUTRAL_DECORATORS for d in sym.decorators):
                continue  # decorators often register the function (routes, fixtures, CLI commands)
            if sym.name in referenced or sym.name in imported_targets:
                continue
            if sym.kind == "method" and method_names.get(sym.name, 0) > 1:
                continue  # likely an override / protocol method
            if sym.kind == "class" and sym.name in subclassed:
                continue
            parent = table.symbols.get(sym.parent) if sym.parent else None
            if (
                parent is not None
                and parent.kind == "class"
                and parent.called_by == []
                and sym.kind == "method"
            ):
                continue  # reported once, at the class
            private = sym.visibility == "private"
            out.append(
                DeadCode(
                    sid,
                    sym.kind,
                    sym.file,
                    sym.lines,
                    "never called, referenced, or imported"
                    + ("" if private else " (public: may be external API)"),
                    "likely" if private else "possible",
                )
            )
        return out
