"""Typed dataclasses shared by every pipeline stage.

Stages communicate only through these types. Nothing here performs I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

SymbolKind = Literal["function", "class", "method"]
Visibility = Literal["public", "private"]
Confidence = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class SourceFile:
    """A file selected by discovery. `path` is repo-relative, POSIX separators."""

    path: str
    language: str
    size: int
    sha256: str
    mtime: float


@dataclass(frozen=True)
class ImportRef:
    """One imported name.

    `import a.b as c`       -> module="a.b", name=None, alias="c"
    `from a.b import c as d` -> module="a.b", name="c", alias="d"
    `from . import x`        -> module="", name="x", level=1
    """

    module: str
    name: str | None
    alias: str | None
    level: int
    line: int

    @property
    def bound_name(self) -> str:
        """The local name this import binds in the importing module."""
        if self.alias:
            return self.alias
        if self.name is not None:
            return self.name
        return self.module.split(".")[0]


@dataclass(frozen=True)
class CallRef:
    """A call site. `target` is the dotted callee expression, e.g. `self.total`."""

    target: str
    line: int


@dataclass(frozen=True)
class EnvRead:
    """A configuration read with a literal key, e.g. `os.environ.get("DATABASE_URL")`."""

    key: str
    line: int
    kind: str = "env"


@dataclass(frozen=True)
class Smell:
    """A cheap static lead for the audit plan. Not a finding."""

    kind: str
    line: int
    detail: str


@dataclass(frozen=True)
class UrlPattern:
    """A Django-style `path("orders/", views.list_orders)` registration."""

    pattern: str
    view: str
    line: int


@dataclass
class ParsedSymbol:
    """A function, class, or method as seen by a parser (file-local names only)."""

    name: str
    qualname: str  # dotted, relative to the module: "Cart.total"
    kind: SymbolKind
    lines: tuple[int, int]
    signature: str
    doc: str
    decorators: list[str] = field(default_factory=list)
    bases: list[str] = field(default_factory=list)
    calls: list[CallRef] = field(default_factory=list)
    parent: str | None = None  # qualname of the enclosing class/function
    tokens_est: int = 0
    local_types: dict[str, str] = field(default_factory=dict)  # var -> dotted type/constructor
    complexity: int = 1  # cyclomatic
    fields: list[tuple[str, str]] = field(default_factory=list)  # class attributes: (name, type)
    env_reads: list[EnvRead] = field(default_factory=list)
    is_async: bool = False
    visibility: str | None = None  # set by parsers whose language decides it (Go, Java, TS)


@dataclass
class ParsedFile:
    """Normalized parser output for one source file."""

    path: str
    language: str
    module: str
    is_package: bool
    line_count: int
    doc: str
    symbols: list[ParsedSymbol] = field(default_factory=list)
    imports: list[ImportRef] = field(default_factory=list)
    module_calls: list[CallRef] = field(default_factory=list)  # calls at module level
    has_main_guard: bool = False
    parse_error: str | None = None
    module_env_reads: list[EnvRead] = field(default_factory=list)
    url_patterns: list[UrlPattern] = field(default_factory=list)
    smells: list[Smell] = field(default_factory=list)
    all_names: list[str] | None = None  # `__all__`, if declared literally
    names_used: list[str] = field(default_factory=list)  # identifiers loaded anywhere (refs)


@dataclass
class Symbol:
    """A symbol in the global table with its fully qualified id."""

    id: str
    name: str
    kind: SymbolKind
    module: str
    file: str
    lines: tuple[int, int]
    signature: str
    doc: str
    visibility: Visibility
    decorators: list[str]
    parent: str | None
    tokens_est: int
    calls: list[str] = field(default_factory=list)
    called_by: list[str] = field(default_factory=list)
    rank: float = 0.0


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    confidence: Confidence = "high"
    line: int | None = None


@dataclass
class ModuleNode:
    id: str
    file: str
    is_package: bool
    doc: str = ""
    loc: int = 0
    imports: list[str] = field(default_factory=list)
    imported_by: list[str] = field(default_factory=list)
    external: list[str] = field(default_factory=list)
    rank: float = 0.0
    entry_point: str | None = None
    community: int = 0


@dataclass
class ImportGraph:
    modules: dict[str, ModuleNode]
    edges: list[Edge]
    external: dict[str, int]


@dataclass
class CallGraph:
    edges: list[Edge]
    unresolved: int
    rank: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class EntryPoint:
    kind: Literal["main_guard", "dunder_main", "console_script", "main_function"]
    module: str
    file: str
    symbol: str | None
    name: str | None = None  # console-script name


@dataclass
class TestsMap:
    test_files: list[str]
    by_symbol: dict[str, list[str]]
    by_file: dict[str, list[str]]


@dataclass(frozen=True)
class Route:
    method: str
    path: str
    handler: str
    file: str
    line: int
    framework: str


@dataclass
class ModelInfo:
    id: str
    file: str
    lines: tuple[int, int]
    framework: str
    fields: list[tuple[str, str]]
    used_by: list[str]


@dataclass(frozen=True)
class ConfigRead:
    symbol: str | None
    file: str
    line: int


@dataclass
class ConfigKey:
    key: str
    kind: str
    reads: list[ConfigRead]


@dataclass(frozen=True)
class DeadCode:
    id: str
    kind: str
    file: str
    lines: tuple[int, int]
    reason: str
    confidence: str  # "likely" | "possible"


@dataclass
class BlastRadius:
    files: dict[str, tuple[int, list[str]]]
    symbols: dict[str, tuple[int, list[str]]]


@dataclass
class GitIntel:
    available: bool
    head: str | None = None
    commits_analyzed: int = 0
    churn: dict[str, int] = field(default_factory=dict)
    owners: dict[str, list[tuple[str, int]]] = field(default_factory=dict)
    last_changed: dict[str, int] = field(default_factory=dict)
    co_change: list[tuple[str, str, int, float]] = field(default_factory=list)


@dataclass
class Health:
    files: dict[str, dict[str, object]]
    symbols: dict[str, dict[str, object]]


@dataclass
class Index:
    """Everything the pipeline knows after a scan; input to the writers."""

    root: str
    files: list[SourceFile]
    parsed: list[ParsedFile]
    symbols: dict[str, Symbol]
    import_graph: ImportGraph
    call_graph: CallGraph
    entry_points: list[EntryPoint]
    tests_map: TestsMap
    languages: dict[str, int]
    project_name: str
    commands: dict[str, str]
    declared_dependencies: list[str] = field(default_factory=list)
    routes: list[Route] = field(default_factory=list)
    models: list[ModelInfo] = field(default_factory=list)
    config: list[ConfigKey] = field(default_factory=list)
    dead_code: list[DeadCode] = field(default_factory=list)
    blast: BlastRadius | None = None
    git: GitIntel | None = None
    health: Health | None = None
    rank_approx: bool = False
