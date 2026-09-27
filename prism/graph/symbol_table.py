"""Symbol table: fully qualified symbol ids and per-module name scopes."""

from __future__ import annotations

from dataclasses import dataclass, field

from prism.core.models import ImportRef, ParsedFile, Symbol, Visibility


def _is_private_name(name: str) -> bool:
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def visibility_for(module: str, qualname: str) -> Visibility:
    parts = [*module.split("."), *qualname.split(".")]
    return "private" if any(_is_private_name(p) for p in parts) else "public"


def resolve_relative(importer: str, importer_is_package: bool, ref: ImportRef) -> str:
    """Absolute dotted module named by an import (without the imported `name`)."""
    if ref.level == 0:
        return ref.module
    package = importer.split(".") if importer_is_package else importer.split(".")[:-1]
    if ref.level > 1:
        package = package[: len(package) - (ref.level - 1)] if ref.level - 1 <= len(package) else []
    base = ".".join(package)
    if ref.module:
        return f"{base}.{ref.module}" if base else ref.module
    return base


@dataclass
class ModuleScope:
    """Names bound at the top level of one module."""

    module: str
    is_package: bool
    defs: dict[str, str] = field(default_factory=dict)  # local name -> symbol id
    bindings: dict[str, str] = field(default_factory=dict)  # local name -> dotted target
    star_imports: list[str] = field(default_factory=list)


DIR_PACKAGE_LANGUAGES = frozenset({"go", "java"})


class ModuleIndex:
    """Lookup of internal module names with a unique-suffix fallback.

    The fallback handles repos whose import root is a subdirectory
    (`backend/app/x.py` imported as `app.x`).
    """

    def __init__(self, modules: list[str]) -> None:
        self.modules = set(modules)
        self._suffix: dict[str, list[str]] = {}
        for mod in sorted(self.modules):
            parts = mod.split(".")
            for i in range(1, len(parts)):
                self._suffix.setdefault(".".join(parts[i:]), []).append(mod)

        # Languages whose unit of import is a directory (Go packages, Java packages):
        # directory name -> the file-level modules inside it.
        self.dir_packages: dict[str, list[str]] = {}

    def find(self, name: str) -> str | None:
        if name in self.modules:
            return name
        candidates = self._suffix.get(name, [])
        return candidates[0] if len(candidates) == 1 else None

    def find_package(self, name: str) -> list[str]:
        """Modules of the directory package `name` (exact, or the longest unique suffix match).

        `example.com.app.internal.store` matches the directory package `internal.store`.
        """
        if name in self.dir_packages:
            return self.dir_packages[name]
        best = [key for key in self.dir_packages if name.endswith("." + key)]
        if not best:
            return []
        longest = max(len(k) for k in best)
        top = [k for k in best if len(k) == longest]
        return self.dir_packages[top[0]] if len(top) == 1 else []

    def package_of(self, module: str) -> list[str]:
        """Sibling modules sharing `module`'s directory package (including itself)."""
        key = module.rsplit(".", 1)[0] if "." in module else ""
        return self.dir_packages.get(key, [])


@dataclass
class SymbolTable:
    symbols: dict[str, Symbol]
    scopes: dict[str, ModuleScope]
    modules: ModuleIndex
    files: dict[str, ParsedFile]  # module -> parsed file


def build_symbol_table(parsed: list[ParsedFile]) -> SymbolTable:
    symbols: dict[str, Symbol] = {}
    scopes: dict[str, ModuleScope] = {}
    files: dict[str, ParsedFile] = {}
    for pf in sorted(parsed, key=lambda p: p.path):
        if pf.module in files:
            continue  # first file wins if two paths map to one module (e.g. .py + .pyi)
        files[pf.module] = pf
        scope = ModuleScope(pf.module, pf.is_package)
        scopes[pf.module] = scope
        for ps in pf.symbols:
            sid = f"{pf.module}.{ps.qualname}"
            symbols[sid] = Symbol(
                id=sid,
                name=ps.name,
                kind=ps.kind,
                module=pf.module,
                file=pf.path,
                lines=ps.lines,
                signature=ps.signature,
                doc=ps.doc,
                visibility="private"
                if ps.visibility == "private"
                else (
                    "public"
                    if ps.visibility == "public"
                    else visibility_for(pf.module, ps.qualname)
                ),
                decorators=list(ps.decorators),
                parent=f"{pf.module}.{ps.parent}" if ps.parent else None,
                tokens_est=ps.tokens_est,
            )
            if ps.parent is None:
                scope.defs[ps.name] = sid
        for ref in pf.imports:
            target_module = resolve_relative(pf.module, pf.is_package, ref)
            if ref.name == "*":
                scope.star_imports.append(target_module)
            elif ref.name is not None:
                scope.bindings[ref.bound_name] = f"{target_module}.{ref.name}"
            elif ref.alias:
                scope.bindings[ref.alias] = ref.module
            else:
                head = ref.module.split(".")[0]
                scope.bindings.setdefault(head, head)
    index = ModuleIndex(list(scopes))
    for mod, pf in sorted(files.items()):
        # Go test files belong to the package but are never part of what importers get.
        if pf.language in DIR_PACKAGE_LANGUAGES and "." in mod and not pf.path.endswith("_test.go"):
            index.dir_packages.setdefault(mod.rsplit(".", 1)[0], []).append(mod)
    return SymbolTable(symbols, scopes, index, files)
