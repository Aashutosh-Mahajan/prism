"""What a packet can say beyond where the code is: twins, a ready patch, read ranges, scope.

Each piece answers a way agents lose calls or get a task wrong:

* **twins**: the same function defined in several files (a copy in `accounts/` and one in
  `patients/`). An agent that edits one copy fails the task, and one that searches for the other
  spends calls finding it. The packet names every copy.
* **patch**: for a mechanical change ("from 23 to 25", "rename a to b") at sites the exact-match
  search found exhaustively, PRISM writes a unified diff under `.aicontext/cache/patches/` and the
  agent applies it with one `git apply`. PRISM only writes text into its own cache; it never edits
  a source file. The diff is checked with `git apply --check` before it is offered.
* **read ranges**: in a large file only the lines around the listed sites need reading.
* **scope**: archived or vendored code, and another part of a monorepo than the request names,
  rank lower.
"""

from __future__ import annotations

import difflib
import hashlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from prism.navigator.source_index import SourceReader
from prism.navigator.store import IndexStore, SymbolRow

# --- scope ---------------------------------------------------------------------------------

ARCHIVE_SEGMENTS = frozenset(
    ["archive", "archived", "legacy", "deprecated", "obsolete", "old", "vendor", "vendored",
     "third_party", "thirdparty", "samples", "sample", "examples", "example", "playground"]
)  # fmt: skip
ARCHIVE_FACTOR = 0.3
AREA_FACTOR = 0.5
# Folder names that mark an area of a monorepo, and the only words of a request that name one.
# A request that merely mentions "the server" or "the API" ("if the server rejects a request ...")
# is describing behaviour, not choosing a part of the repository, so those words do not count.
_AREAS: dict[str, frozenset[str]] = {
    "backend": frozenset(["backend", "server", "api", "service", "services"]),
    "frontend": frozenset(["frontend", "client", "web", "webapp", "ui", "www", "website"]),
    "mobile": frozenset(["mobile", "android", "ios", "flutter", "app_mobile"]),
}
_AREA_WORDS: dict[str, frozenset[str]] = {
    "backend": frozenset(["backend", "back-end"]),
    "frontend": frozenset(["frontend", "front-end"]),
    "mobile": frozenset(["mobile"]),
}
_WORD = re.compile(r"[a-z][a-z_]+")


def _request_areas(query: str) -> set[str]:
    lowered = query.lower()
    words = set(_WORD.findall(lowered)) | {
        w for names in _AREA_WORDS.values() for w in names if w in lowered
    }
    return {area for area, names in _AREA_WORDS.items() if words & names}


def scope_factor(query: str, path: str) -> float:
    """1.0 for ordinary code; lower for archived code and for another area than the request names.

    The request may name what it wants ("update the backend validation"): code under `archive/`
    is demoted unless the request mentions it, and so is the top-level area (frontend, mobile)
    the request did not name, when it names exactly one."""
    segments = [s.lower() for s in path.split("/")[:-1]]
    words = set(_WORD.findall(query.lower()))
    factor = 1.0
    if any(s in ARCHIVE_SEGMENTS and s not in words for s in segments):
        factor *= ARCHIVE_FACTOR
    areas = _request_areas(query)
    if len(areas) == 1 and segments:
        top = segments[0]
        owner = next((area for area, names in _AREAS.items() if top in names), None)
        if owner is not None and owner not in areas:
            factor *= AREA_FACTOR
    return factor


# --- twins ---------------------------------------------------------------------------------

TWIN_THRESHOLD = 0.80  # bodies this alike are copies whatever the signature
SAME_SIGNATURE_THRESHOLD = 0.65  # same name and signature: parallel definitions, edited together
MAX_SAME_NAME = 6  # more definitions than this is an interface or a convention, not a copy
GENERIC_NAMES = frozenset(
    ["get", "set", "run", "main", "init", "setup", "teardown", "handle", "post", "put", "delete",
     "patch", "list", "create", "update", "save", "load", "render", "call", "apply", "close",
     "open", "read", "write", "start", "stop", "build", "parse", "validate", "process", "execute"]
)  # fmt: skip
MAX_TWIN_TOKENS = 700
MAX_TWIN_COPIES = 4
_CODE_TOKEN = re.compile(r"[A-Za-z_]\w*|\d+|\S")


def _tokens(lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "//", "*", "/*")):
            continue
        out.extend(_CODE_TOKEN.findall(stripped))
    return out


def _similarity(a: list[str], b: list[str]) -> float:
    if not a or not b:
        return 0.0
    if len(a) > MAX_TWIN_TOKENS or len(b) > MAX_TWIN_TOKENS:
        grams_a = {tuple(a[i : i + 3]) for i in range(len(a) - 2)}
        grams_b = {tuple(b[i : i + 3]) for i in range(len(b) - 2)}
        union = grams_a | grams_b
        return len(grams_a & grams_b) / len(union) if union else 0.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def find_twins(
    store: IndexStore, reader: SourceReader, symbols: list[SymbolRow]
) -> list[dict[str, Any]]:
    """Other definitions of the same function or method with a near-identical body.

    For each of `symbols` (the packet's primary functions): every symbol of the same name and kind
    in another file whose body, ignoring comments and layout, is at least 80% the same. Tests are
    compared only with tests."""
    found: list[dict[str, Any]] = []
    seen_names: set[tuple[str, str]] = set()
    for sym in symbols:
        if sym.kind not in ("function", "method") or (sym.name, sym.kind) in seen_names:
            continue
        if sym.name.startswith("__") or sym.name.lower() in GENERIC_NAMES or len(sym.name) < 6:
            continue
        seen_names.add((sym.name, sym.kind))
        own_lines = reader.lines(sym.file)
        if own_lines is None:
            continue
        own = _tokens(own_lines[sym.start - 1 : sym.end])
        is_test = store._is_test(sym.file)
        copies: list[dict[str, Any]] = []
        same_name = store.symbols_named(sym.name)
        if len(same_name) > MAX_SAME_NAME:
            continue
        signature = " ".join(sym.signature.split())
        for other in same_name:
            if other.id == sym.id or other.file == sym.file or other.kind != sym.kind:
                continue
            if store._is_test(other.file) != is_test:
                continue
            other_lines = reader.lines(other.file)
            if other_lines is None:
                continue
            ratio = _similarity(own, _tokens(other_lines[other.start - 1 : other.end]))
            parallel = " ".join(other.signature.split()) == signature
            if ratio >= TWIN_THRESHOLD or (parallel and ratio >= SAME_SIGNATURE_THRESHOLD):
                copies.append(
                    {
                        "file": other.file,
                        "lines": [other.start, other.end],
                        "similarity": round(ratio, 2),
                    }
                )
        if copies:
            copies.sort(key=lambda c: (-c["similarity"], c["file"]))
            found.append(
                {
                    "name": sym.name,
                    "primary": {"file": sym.file, "lines": [sym.start, sym.end]},
                    "copies": copies[:MAX_TWIN_COPIES],
                }
            )
    return found


# --- read ranges ---------------------------------------------------------------------------

LARGE_FILE_LINES = 600
RANGE_PAD = 20
RANGE_GAP = 40
MAX_RANGES_PER_FILE = 3
MAX_RANGES = 6


def read_ranges(reader: SourceReader, sites: dict[str, list[int]]) -> list[dict[str, Any]]:
    """`Read` windows (offset = first line, limit = line count) around sites in large files."""
    ranges: list[dict[str, Any]] = []
    for file, lines_at in sorted(sites.items()):
        lines = reader.lines(file)
        if lines is None or len(lines) < LARGE_FILE_LINES:
            continue
        windows: list[list[int]] = []
        for line in sorted(set(lines_at)):
            lo, hi = max(1, line - RANGE_PAD), min(len(lines), line + RANGE_PAD)
            if windows and lo - windows[-1][1] <= RANGE_GAP and hi - windows[-1][0] + 1 <= 120:
                windows[-1][1] = max(windows[-1][1], hi)
            else:
                windows.append([lo, hi])
        if len(windows) > MAX_RANGES_PER_FILE:
            # Hints stay bounded even for scattered sites; the packet's exhaustive
            # site list remains the authority for any additional windows needed.
            windows = windows[:MAX_RANGES_PER_FILE]
        for lo, hi in windows:
            ranges.append({"file": file, "offset": lo, "limit": hi - lo + 1, "total": len(lines)})
        if len(ranges) >= MAX_RANGES:
            break
    return ranges[:MAX_RANGES]


# --- mechanical replacements ---------------------------------------------------------------


@dataclass(frozen=True)
class Replacement:
    old: str
    new: str
    kind: str  # "number" | "identifier"


_NUM = r"\d+(?:\.\d+)?"
_FROM_TO = re.compile(
    rf"\bfrom\s+(?P<old>{_NUM})\b(?:\s+[A-Za-z%]+)?\s+to\s+(?P<new>{_NUM})\b", re.IGNORECASE
)
_ARROW = re.compile(rf"(?<![\w.])(?P<old>{_NUM})\s*(?:->|→|=>)\s*(?P<new>{_NUM})\b")
_INSTEAD = re.compile(
    rf"\b(?P<new>{_NUM})\b(?:\s+[A-Za-z%]+)?\s+(?:instead\s+of|rather\s+than)\s+(?P<old>{_NUM})\b",
    re.IGNORECASE,
)
_RENAME = re.compile(
    r"\brename\s+(?:the\s+)?(?:(?:function|method|class|variable|field|helper|symbol)\s+)?"
    r"(?P<old>[A-Za-z_]\w*)\s+(?:to|as|into)\s+(?P<new>[A-Za-z_]\w*)\b",
    re.IGNORECASE,
)


def parse_replacements(query: str) -> list[Replacement]:
    """Explicit old → new changes in a request: numbers ("from 23 to 25") and renames."""
    found: list[Replacement] = []
    for pattern in (_FROM_TO, _ARROW, _INSTEAD):
        for m in pattern.finditer(query):
            old, new = m.group("old"), m.group("new")
            if old != new:
                found.append(Replacement(old, new, "number"))
    for m in _RENAME.finditer(query):
        old, new = m.group("old"), m.group("new")
        if old != new:
            found.append(Replacement(old, new, "identifier"))
    unique: dict[tuple[str, str, str], Replacement] = {}
    for item in found:
        unique.setdefault((item.old, item.new, item.kind), item)
    return list(unique.values())[:3]


def _pattern(item: Replacement) -> re.Pattern[str]:
    if item.kind == "number":
        return re.compile(rf"(?<![\w.]){re.escape(item.old)}(?!\w|\.\d)")
    return re.compile(rf"(?<!\w){re.escape(item.old)}(?!\w)")


# The patch is byte-exact (it keeps each file's own line endings), so it is applied without git's
# line-ending conversion: with `core.autocrlf` set, a plain `git apply` rewrites whole files.
APPLY_COMMAND = "git -c core.autocrlf=false apply"
PATCH_DIR = "patches"
KEEP_PATCHES = 20
CONTEXT = 3


def _split_raw(data: bytes) -> list[bytes]:
    parts = data.split(b"\n")
    lines = [p + b"\n" for p in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def _emit(prefix: bytes, raw: bytes) -> bytes:
    if raw.endswith(b"\n"):
        return prefix + raw
    return prefix + raw + b"\n\\ No newline at end of file\n"


def unified_diff(file: str, old: list[bytes], changed: dict[int, bytes]) -> bytes:
    """A git-style diff of single-line substitutions in `old` (1-based line numbers)."""
    if not changed:
        return b""
    rows = sorted(changed)
    groups: list[list[int]] = [[rows[0]]]
    for row in rows[1:]:
        if row - groups[-1][-1] <= 2 * CONTEXT:
            groups[-1].append(row)
        else:
            groups.append([row])
    out = bytearray()
    name = file.encode("utf-8")
    out += b"diff --git a/" + name + b" b/" + name + b"\n--- a/" + name + b"\n+++ b/" + name + b"\n"
    for group in groups:
        first, last = max(1, group[0] - CONTEXT), min(len(old), group[-1] + CONTEXT)
        count = last - first + 1
        out += f"@@ -{first},{count} +{first},{count} @@\n".encode()
        number = first
        while number <= last:
            if number in changed:
                run = [number]
                while run[-1] + 1 in changed and run[-1] + 1 <= last:
                    run.append(run[-1] + 1)
                for n in run:
                    out += _emit(b"-", old[n - 1])
                for n in run:
                    out += _emit(b"+", changed[n])
                number = run[-1] + 1
            else:
                out += _emit(b" ", old[number - 1])
                number += 1
    return bytes(out)


def _git_accepts(root: Path, patch: Path) -> bool:
    try:
        done = subprocess.run(
            [
                "git",
                "-c",
                "core.autocrlf=false",
                "apply",
                "--check",
                "--numstat",
                "--whitespace=nowarn",
                str(patch),
            ],
            cwd=root,
            capture_output=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    # Git may succeed while skipping every path when called in a subdirectory.
    return done.returncode == 0 and bool(done.stdout.strip())


def _patch_prefix(root: Path) -> str:
    """Git interprets diff paths relative to its worktree, even from a subfolder."""
    try:
        done = subprocess.run(
            ["git", "rev-parse", "--show-prefix"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return done.stdout.strip() if done.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def build_patch(
    store: IndexStore, reader: SourceReader, query: str, evidence: Any
) -> dict[str, Any] | None:
    """A checked patch for the request's explicit replacements at their exhaustive sites.

    Returns {path, sites, files, old, new} or None when there is nothing safe to offer: no explicit
    old → new, a literal list that is not exhaustive, a line that no longer matches the index, a
    new name that already exists, or a diff `git apply --check` rejects."""
    replacements = parse_replacements(query)
    if not replacements:
        return None
    if len({item.old for item in replacements}) != len(replacements):
        return None  # conflicting destinations must never be guessed
    edits: dict[str, set[int]] = {}
    used: list[Replacement] = []
    for item in replacements:
        sites: dict[tuple[str, int], str] = {}
        for lit in evidence.literals:
            if not lit.complete:
                continue
            head = lit.text.split(" ", 1)[0]
            if (
                item.kind == "number" and (lit.kind in ("number", "quantity")) and head == item.old
            ) or (item.kind == "identifier" and lit.kind == "identifier" and lit.text == item.old):
                pass
            else:
                continue
            for occ in lit.occurrences:
                sites[(occ.file, occ.line)] = occ.text
        if not sites:
            return None  # never offer only part of the explicitly requested substitutions
        if item.kind == "identifier" and item.new not in set(evidence.absent):
            return None  # the new name already exists: a blind rename could merge two things
        for (file, line), indexed_text in sorted(sites.items()):
            indexed = reader.lines(file)
            if indexed is None or line > len(indexed):
                return None
            if " ".join(indexed[line - 1].split()) != " ".join(indexed_text.split()):
                return None
            edits.setdefault(file, set()).add(line)
        used.append(item)
    if not edits or not used:
        return None

    patch = bytearray()
    prefix = _patch_prefix(store.root)
    total_sites = 0
    for file in sorted(edits):
        path = store.root / file
        try:
            data = path.read_bytes()
            raw = _split_raw(data)
        except OSError:
            return None
        changed: dict[int, bytes] = {}
        for line in sorted(edits[file]):
            if line > len(raw):
                return None
            original = raw[line - 1]
            body = original.rstrip(b"\r\n")
            eol = original[len(body) :]
            try:
                text = body.decode("utf-8")
            except UnicodeDecodeError:
                return None
            # All substitutions inspect the original text, so 10 -> 20 and
            # 20 -> 30 cannot cascade into 10 -> 30.
            pattern = re.compile(
                "|".join(f"(?P<r{i}>{_pattern(item).pattern})" for i, item in enumerate(used))
            )
            new_text = pattern.sub(lambda match: used[int((match.lastgroup or "r0")[1:])].new, text)
            if new_text == text:
                return None  # the indexed line does not contain the old value any more
            changed[line] = new_text.encode("utf-8") + eol
        total_sites += len(changed)
        patch += unified_diff(prefix + file, raw, changed)
    if not patch:
        return None

    from prism.consent import cache_root

    digest = hashlib.sha256(bytes(patch)).hexdigest()[:12]
    directory = cache_root(store.root) / PATCH_DIR
    target = directory / f"{digest}.patch"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        target.write_bytes(bytes(patch))
    except OSError:
        return None
    if not _git_accepts(store.root, target):
        target.unlink(missing_ok=True)
        return None
    _prune(directory)
    try:
        shown = target.relative_to(store.root).as_posix()
    except ValueError:
        shown = target.as_posix()
    return {
        "path": shown,
        "sites": total_sites,
        "files": len(edits),
        "old": used[0].old if len(used) == 1 else ", ".join(i.old for i in used),
        "new": used[0].new if len(used) == 1 else ", ".join(i.new for i in used),
    }


def _prune(directory: Path) -> None:
    try:
        files = sorted(directory.glob("*.patch"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[KEEP_PATCHES:]:
            old.unlink(missing_ok=True)
    except OSError:
        pass
