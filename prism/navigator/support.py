"""Source-verified local definitions needed to interpret a retrieved Python body."""

from __future__ import annotations

import ast
from dataclasses import dataclass

from prism.navigator.source_index import SourceReader

MAX_SUPPORT = 4
MAX_FILE_CHARS = 200_000


@dataclass(frozen=True)
class SupportRange:
    file: str
    start: int
    end: int
    name: str


def local_support(
    reader: SourceReader, file: str, ranges: list[tuple[int, int]]
) -> list[SupportRange]:
    """Resolve loaded names to top-level constants/imports/helpers, not whole headers.

    The AST is built from hash-verified source, never executed. A name is included
    only if used by a selected body and not already defined in that body. Results
    have deterministic limits and are fitted to the shared answer budget later.
    """
    if not file.endswith((".py", ".pyi")):
        return []
    lines = reader.lines(file)
    if not lines or sum(map(len, lines)) > MAX_FILE_CHARS:
        return []
    try:
        tree = ast.parse("\n".join(lines))
    except (SyntaxError, ValueError, RecursionError):
        return []
    loaded: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and any(start <= node.lineno <= end for start, end in ranges)
        ):
            loaded.add(node.id)
    candidates: list[SupportRange] = []
    for node in tree.body:
        start, end = node.lineno, node.end_lineno or node.lineno
        if any(lo <= start and end <= hi for lo, hi in ranges):
            continue
        names: list[str] = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names = [node.name]
            if node.decorator_list:
                start = min(start, *(d.lineno for d in node.decorator_list))
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.asname or alias.name.split(".", 1)[0] for alias in node.names]
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = [
                child.id
                for target in targets
                for child in ast.walk(target)
                if isinstance(child, ast.Name)
            ]
        wanted = sorted(loaded & set(names))
        if wanted and end - start < 60:
            candidates.append(SupportRange(file, start, end, ", ".join(wanted)))
    # Constants/helper bodies first; import lines remain useful but usually add
    # less information. No prose comments or unrelated declarations are copied.
    candidates.sort(
        key=lambda item: (
            lines[item.start - 1].lstrip().startswith(("import ", "from ")),
            item.start,
        )
    )
    return candidates[:MAX_SUPPORT]
