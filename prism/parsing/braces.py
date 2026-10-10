"""Dependency-free parsers for brace languages without a tree-sitter grammar: Dart, Kotlin, Swift.

They read the declarations that matter for navigation: classes (and their kin), functions and
methods with exact line ranges, doc comments, base types, imports and call sites. The source is
first *masked* (comments, strings and character literals replaced by spaces, newlines kept) so
braces and keywords inside them can never confuse the scan. A grammar would be more exact; this
is deterministic, installs nothing, and is checked on fixtures.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from typing import ClassVar

from prism.core.models import CallRef, ImportRef, ParsedFile, ParsedSymbol, Smell, SymbolKind
from prism.core.textio import decode_source
from prism.core.tokens import estimate_tokens
from prism.parsing.base_parser import BaseParser

KEYWORDS = frozenset(
    [
        "if",
        "else",
        "for",
        "while",
        "do",
        "switch",
        "case",
        "when",
        "guard",
        "catch",
        "try",
        "finally",
        "return",
        "throw",
        "break",
        "continue",
        "super",
        "this",
        "self",
        "new",
        "await",
        "async",
        "yield",
        "is",
        "as",
        "in",
        "assert",
        "defer",
        "where",
        "let",
        "var",
        "val",
        "const",
        "final",
        "late",
        "static",
        "print",
        "typeof",
        "sizeof",
        "fun",
        "func",
        "class",
        "struct",
        "enum",
        "interface",
        "object",
        "init",
        "get",
        "set",
        "else",
    ]
)
DECISION = re.compile(
    r"\b(?:if|for|while|case|when|catch|guard)\b|&&|\|\||\?\?|(?<![?\w])\?(?![?.:])"
)
_IDENT = re.compile(r"[^\W\d]\w*")
_CALL = re.compile(
    r"(?<![\w.])((?:[^\W\d]\w*\s*(?:\?\.|!\.|\.))*[^\W\d]\w*)\s*(?:<[^<>()]*>)?\s*[({]"
)
_TODO = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b")


def mask_source(text: str, interpolation: tuple[str, ...]) -> str:
    """`text` with comments, strings and char literals blanked (newlines kept, same length)."""
    out: list[str] = []
    n = len(text)
    i = 0

    def blank(chunk: str) -> str:
        return "".join(c if c == "\n" else " " for c in chunk)

    def string(start: int) -> int:
        """End index (exclusive) of the string literal beginning at `start`."""
        quote = text[start]
        triple = text.startswith(quote * 3, start)
        raw = start > 0 and text[start - 1] == "r" and quote in "'\""
        j = start + (3 if triple else 1)
        while j < n:
            c = text[j]
            if c == "\\" and not raw:
                j += 2
                continue
            if triple and text.startswith(quote * 3, j):
                return j + 3
            if not triple and c == quote:
                return j + 1
            if not triple and c == "\n" and quote != "`":
                return j  # an unterminated one-line string ends at the line
            opener = next((o for o in interpolation if text.startswith(o, j)), None)
            if opener and not raw:
                depth = 1
                j += len(opener)
                while j < n and depth:
                    if text[j] in "'\"":
                        j = string(j)
                        continue
                    depth += (text[j] in "{(") - (text[j] in "})")
                    j += 1
                continue
            j += 1
        return n

    while i < n:
        c = text[i]
        if c == "/" and text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(blank(text[i:j]))
            i = j
        elif c == "/" and text.startswith("/*", i):
            depth, j = 1, i + 2
            while j < n and depth:
                if text.startswith("/*", j):
                    depth += 1
                    j += 2
                elif text.startswith("*/", j):
                    depth -= 1
                    j += 2
                else:
                    j += 1
            out.append(blank(text[i:j]))
            i = j
        elif c in "'\"":
            if c == "'" and i + 2 < n and text[i + 2] == "'" and "\n" not in text[i : i + 3]:
                j = i + 3  # a char literal such as 'x'
            else:
                j = string(i)
            out.append(c + blank(text[i + 1 : j - 1]) + c if j - i >= 2 else blank(text[i:j]))
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


@dataclass
class _Container:
    qualname: str
    depth: int  # brace depth of its body
    end_line: int


class BraceLanguageParser(BaseParser):
    """Shared scan; subclasses provide the declaration patterns."""

    language: str
    interpolation: ClassVar[tuple[str, ...]] = ("${",)
    container: ClassVar[re.Pattern[str]]
    function: ClassVar[re.Pattern[str]]
    import_line: ClassVar[re.Pattern[str]]
    private_marker: ClassVar[str] = "private"
    extra_function: ClassVar[re.Pattern[str] | None] = None

    # --- language hooks ----------------------------------------------------------------

    def imports_of(self, line: str, number: int, module: str, is_package: bool) -> list[ImportRef]:
        return []

    def visibility(self, header: str, name: str) -> str:
        return "private" if re.search(rf"\b{self.private_marker}\b", header) else "public"

    def bases(self, header: str) -> list[str]:
        return []

    # --- scan --------------------------------------------------------------------------

    def parse(self, path: str, source: bytes, module: str, is_package: bool) -> ParsedFile:
        text = decode_source(source)
        lines = text.splitlines()
        line_count = text.count("\n") + (0 if text.endswith("\n") or not text else 1)
        result = ParsedFile(path, self.language, module, is_package, line_count, "")
        masked = mask_source(text, self.interpolation)
        mlines = masked.splitlines()
        # brace depth at the start of every line, and the line where each `{` closes
        depth_at: list[int] = []
        stack: list[int] = []
        closes: dict[int, int] = {}  # opening line -> closing line (first `{` on that line)
        depth = 0
        for number, line in enumerate(mlines, 1):
            depth_at.append(depth)
            for ch in line:
                if ch == "{":
                    stack.append(number)
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if stack:
                        opened = stack.pop()
                        closes.setdefault(opened, number)
                    if depth < 0:
                        depth = 0
        if depth != 0 or stack:
            result.parse_error = "SyntaxError: unbalanced braces"
        symbols: list[ParsedSymbol] = []
        containers: list[_Container] = []
        imports: list[ImportRef] = []
        smells: list[Smell] = []
        for number, raw in enumerate(lines, 1):
            m = _TODO.search(raw)
            if m and ("//" in raw or "/*" in raw or "*" in raw.lstrip()[:2]):
                smells.append(Smell("todo", number, raw.strip()[:120]))
        i = 0
        total = len(mlines)
        while i < total:
            number = i + 1
            line = mlines[i]
            depth = depth_at[i]
            while containers and (number > containers[-1].end_line or depth < containers[-1].depth):
                containers.pop()
            for ref in self.imports_of(line, number, module, is_package):
                imports.append(ref)
            parent = containers[-1] if containers else None
            if parent is not None and depth != parent.depth:
                i += 1
                continue
            if parent is None and depth != 0:
                i += 1
                continue
            header = self._header(mlines, i)
            cm = self.container.match(header)
            fm = None if cm else self.function.match(header)
            if fm is None and cm is None and self.extra_function is not None:
                fm = self.extra_function.match(header)
            if cm is None and fm is None:
                i += 1
                continue
            match = cm or fm
            assert match is not None
            groups = match.groupdict()
            name = groups.get("name") or groups.get("init") or ""
            if not name or (name in KEYWORDS and cm is None and name != "init"):
                i += 1
                continue
            end = self._end_line(mlines, i, closes)
            start = self._with_leading(lines, i)
            qual = f"{parent.qualname}.{name}" if parent else name
            kind: SymbolKind = "class" if cm else ("method" if parent else "function")
            body = "\n".join(mlines[i:end])
            sig = " ".join(header.split())[:200]
            sym = ParsedSymbol(
                name=name,
                qualname=qual,
                kind=kind,
                lines=(start + 1, end),
                signature=sig,
                doc=self._doc(lines, start),
                bases=self.bases(header) if cm else [],
                calls=[] if cm else self._calls(mlines, i, end),
                parent=parent.qualname if parent else None,
                tokens_est=estimate_tokens("\n".join(lines[start:end])),
                complexity=1 if cm else 1 + len(DECISION.findall(body)),
                is_async=bool(re.search(r"\basync\b|\bsuspend\b", header)),
                visibility=self.visibility(header, name),
            )
            if cm and any(x.qualname == qual and x.kind == "class" for x in symbols):
                containers.append(_Container(qual, depth + 1, end))  # an extension of a known type
                i += 1
                continue
            symbols.append(sym)
            if cm:
                containers.append(_Container(qual, depth + 1, end))
                i += 1  # members are scanned line by line
                continue
            i = max(end, i + 1)  # a function body is not scanned for declarations
        result.symbols = symbols
        result.imports = sorted(set(imports), key=lambda r: (r.line, r.module, r.name or ""))
        inside = [(s.lines[0], s.lines[1]) for s in symbols if s.kind != "class"]
        module_calls: list[CallRef] = []
        for number, line in enumerate(mlines, 1):
            if any(a <= number <= b for a, b in inside) or self.import_line.match(line):
                continue
            if depth_at[number - 1] == 0 and not self.container.match(line):
                module_calls.extend(self._calls(mlines, number - 1, number))
        result.module_calls = sorted(set(module_calls), key=lambda c: (c.line, c.target))
        result.smells = smells
        result.names_used = sorted(set(_IDENT.findall(masked)))
        first = next((ln.strip() for ln in lines if ln.strip()), "")
        if first.startswith(("///", "//", "/*")):
            result.doc = first.lstrip("/*! ").strip()[:200]
        return result

    # --- helpers -----------------------------------------------------------------------

    @staticmethod
    def _header(mlines: list[str], i: int) -> str:
        """The declaration starting at line `i`, joined across lines until its parameters close."""
        text = mlines[i]
        j = i
        while text.count("(") > text.count(")") and j + 1 < len(mlines) and j - i < 12:
            j += 1
            text += " " + mlines[j].strip()
        return text.strip()

    @staticmethod
    def _end_line(mlines: list[str], i: int, closes: dict[int, int]) -> int:
        """1-based last line of the declaration beginning at 0-based line `i`."""
        j = i
        limit = min(len(mlines), i + 14)
        while j < limit:
            line = mlines[j]
            if "{" in line:
                return closes.get(j + 1, len(mlines))
            if ";" in line or ("=>" in line and not line.rstrip().endswith(("=>", "(", ","))):
                return j + 1
            if j > i and not line.strip():
                return j
            j += 1
        return i + 1

    @staticmethod
    def _with_leading(lines: list[str], i: int) -> int:
        """0-based first line including doc comments and annotations directly above."""
        j = i
        while j > 0:
            prev = lines[j - 1].strip()
            if prev.startswith(("///", "//", "/**", "*", "*/", "@")) or prev.endswith("*/"):
                j -= 1
                continue
            break
        return j

    @staticmethod
    def _doc(lines: list[str], start: int) -> str:
        for k in range(start, min(start + 6, len(lines))):
            s = lines[k].strip()
            if s.startswith(("///", "/**", "*", "//")):
                cleaned = s.lstrip("/*! ").rstrip("*/ ").strip()
                if cleaned and not cleaned.startswith("@"):
                    return cleaned[:200]
            elif s:
                break
        return ""

    @staticmethod
    def _calls(mlines: list[str], i: int, end: int) -> list[CallRef]:
        calls: list[CallRef] = []
        for k in range(i, min(end, len(mlines))):
            for m in _CALL.finditer(mlines[k]):
                target = re.sub(r"\s*(\?\.|!\.)\s*", ".", m.group(1)).replace(" ", "")
                head = target.split(".")[0]
                if head in KEYWORDS or target.rsplit(".", 1)[-1] in KEYWORDS:
                    continue
                calls.append(CallRef(target, k + 1))
        return sorted(set(calls), key=lambda c: (c.line, c.target))


def _relative(importer: str, is_package: bool, spec: str, exts: tuple[str, ...]) -> str:
    for ext in exts:
        if spec.endswith(ext):
            spec = spec[: -len(ext)]
            break
    base = importer.split(".") if is_package else importer.split(".")[:-1]
    joined = posixpath.normpath(posixpath.join("/".join(base) or ".", spec))
    return ".".join(p for p in joined.split("/") if p and p != ".")


class DartParser(BraceLanguageParser):
    language = "dart"
    interpolation = ("${",)
    container = re.compile(
        r"^\s*(?:@\w+(?:\([^)]*\))?\s+)*(?:(?:abstract|sealed|base|final|interface|mixin|macro)\s+)*"
        r"(?:class|mixin|enum|extension(?:\s+type)?)\s+(?P<name>[A-Za-z_]\w*)"
    )
    function = re.compile(
        r"^\s*(?:@\w+(?:\([^)]*\))?\s+)*(?:(?:static|external|abstract|factory|const|override|late)\s+)*"
        r"(?:[\w<>\[\]?,.\s]+?\s+)?(?:(?:get|set)\s+)?"
        r"(?P<name>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)\s*(?:<[^<>=]*>)?\s*\("
    )
    extra_function = re.compile(
        r"^\s*(?:@\w+(?:\([^)]*\))?\s+)*(?:(?:static|external|abstract|override)\s+)*"
        r"(?:[\w<>\[\]?,.\s]+?\s+)?(?:get|set)\s+(?P<name>[A-Za-z_]\w*)\s*(?:=>|\{|;)"
    )
    import_line = re.compile(r"^\s*(?:import|export|part)\s+['\"]")
    private_marker = "_private_"  # Dart privacy is the leading underscore, decided below

    def visibility(self, header: str, name: str) -> str:
        return "private" if name.startswith("_") else "public"

    def bases(self, header: str) -> list[str]:
        out: list[str] = []
        for clause in re.finditer(
            r"\b(?:extends|with|implements|on)\s+([^{]+?)(?=\b(?:extends|with|implements|on)\b|\{|$)",
            header,
        ):
            out.extend(
                n for n in re.findall(r"[A-Za-z_]\w*", re.sub(r"<[^<>]*>", "", clause.group(1)))
            )
        return out

    def imports_of(self, line: str, number: int, module: str, is_package: bool) -> list[ImportRef]:
        return []  # Dart imports are string literals, which masking blanks: see parse override

    def parse(self, path: str, source: bytes, module: str, is_package: bool) -> ParsedFile:
        result = super().parse(path, source, module, is_package)
        text = decode_source(source)
        refs: list[ImportRef] = []
        for number, line in enumerate(text.splitlines(), 1):
            m = re.match(r"\s*(?:import|export)\s+['\"]([^'\"]+)['\"](?:\s+as\s+(\w+))?", line)
            if not m:
                continue
            spec, alias = m.group(1), m.group(2)
            if spec.startswith("dart:"):
                continue
            if spec.startswith("package:"):
                _package, _, rest = spec[len("package:") :].partition("/")
                target = "lib." + rest.removesuffix(".dart").replace("/", ".")
                refs.append(ImportRef(target, None, alias, 0, number))
            else:
                refs.append(
                    ImportRef(
                        _relative(module, is_package, spec, (".dart",)), None, alias, 0, number
                    )
                )
        result.imports = sorted(set(refs), key=lambda r: (r.line, r.module))
        return result


class KotlinParser(BraceLanguageParser):
    language = "kotlin"
    interpolation = ("${",)
    container = re.compile(
        r"^\s*(?:@\w+(?:\([^)]*\))?\s+)*(?:(?:public|private|protected|internal|data|sealed|enum|annotation|"
        r"inner|value|abstract|open|inline|fun|companion|expect|actual)\s+)*"
        r"(?:class|interface|object)\s+(?P<name>[A-Za-z_]\w*)"
    )
    function = re.compile(
        r"^\s*(?:@\w+(?:\([^)]*\))?\s+)*(?:(?:public|private|protected|internal|override|open|abstract|final|"
        r"inline|suspend|operator|infix|tailrec|external|actual|expect|lateinit)\s+)*"
        r"fun\s+(?:<[^<>]*>\s*)?(?:[\w<>?.,\s]+\.)?(?P<name>[A-Za-z_]\w*)\s*\("
    )
    import_line = re.compile(r"^\s*(?:import|package)\s+")

    def bases(self, header: str) -> list[str]:
        after = header.split(":", 1)[1] if ":" in header else ""
        after = re.sub(r"\([^)]*\)", "", after.split("{", 1)[0])
        return [n for n in re.findall(r"[A-Za-z_]\w*", re.sub(r"<[^<>]*>", "", after))]

    def imports_of(self, line: str, number: int, module: str, is_package: bool) -> list[ImportRef]:
        m = re.match(r"\s*import\s+([\w.]+?)(?:\.\*)?(?:\s+as\s+(\w+))?\s*$", line)
        if not m:
            return []
        dotted, alias = m.group(1), m.group(2)
        if line.rstrip().endswith("*"):
            return [ImportRef(dotted, "*", None, 0, number)]
        head, _, last = dotted.rpartition(".")
        return [ImportRef(head or dotted, last if head else None, alias, 0, number)]


class SwiftParser(BraceLanguageParser):
    language = "swift"
    interpolation = ("\\(",)
    container = re.compile(
        r"^\s*(?:@\w+(?:\([^)]*\))?\s+)*(?:(?:public|private|fileprivate|internal|open|final|indirect)\s+)*"
        r"(?:class|struct|enum|protocol|extension|actor)\s+(?P<name>[A-Za-z_][\w.]*)"
    )
    function = re.compile(
        r"^\s*(?:@\w+(?:\([^)]*\))?\s+)*(?:(?:public|private|fileprivate|internal|open|final|static|class|"
        r"override|mutating|nonmutating|convenience|required|nonisolated)\s+)*"
        r"(?:func\s+(?P<name>[A-Za-z_]\w*|[^\s\w(<]+)\s*(?:<[^<>]*>)?\s*\(|(?P<init>init)\s*[?!]?\s*\()"
    )
    import_line = re.compile(r"^\s*import\s+")
    private_marker = "(?:private|fileprivate)"

    def bases(self, header: str) -> list[str]:
        after = header.split(":", 1)[1] if ":" in header else ""
        after = after.split("{", 1)[0].split(" where ", 1)[0]
        return [n for n in re.findall(r"[A-Za-z_]\w*", re.sub(r"<[^<>]*>", "", after))]

    def imports_of(self, line: str, number: int, module: str, is_package: bool) -> list[ImportRef]:
        m = re.match(
            r"\s*import\s+(?:(?:class|struct|enum|protocol|func|var|let|typealias)\s+)?([\w.]+)",
            line,
        )
        return [ImportRef(m.group(1), None, None, 0, number)] if m else []


def parsers() -> list[BaseParser]:
    return [DartParser(), KotlinParser(), SwiftParser()]
