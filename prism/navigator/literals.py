"""Evidence evidence: exact strings, identifiers and quantities named in a request.

A grep is the one thing an agent always trusts, and for a literal string it is hard to beat.
This module makes `prism task` a superset of the greps an agent would run: every occurrence of
each literal in the indexed source is found (via the postings, without scanning the repository),
listed with file:line, and reported with a total so the agent can tell the list is exhaustive.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field, replace
from typing import Any

from prism.core.textio import decode_source, normalize
from prism.navigator.source_index import SourceIndex, SourceReader
from prism.navigator.text import FILLER_WORDS, stem, tokenize

MAX_OCCURRENCES_SCANNED = 200  # per literal; beyond this a literal is too common to be evidence
MAX_FILES_PER_LITERAL = 80
MAX_PHRASE_LINES = 8  # an unquoted phrase found on more lines than this is generic prose
MAX_NAMED_LINES = 40  # quoted strings and identifiers the user typed are kept longer
MAX_PHRASE_CANDIDATES = 120
MAX_LITERALS = 6
LINE_CHARS = 110

QUANTITY_UNITS = frozenset(
    [
        "minute", "minutes", "min", "mins", "second", "seconds", "sec", "secs",
        "hour", "hours", "hr", "hrs", "day", "days", "week", "weeks", "month", "months",
        "year", "years", "attempt", "attempts", "retry", "retries", "character", "characters",
        "char", "chars", "item", "items", "page", "pages", "px", "ms", "mb", "kb", "gb",
    ]
)  # fmt: skip

_QUOTED = re.compile(
    r"""(?<![\w])(?:'([^'\n]{2,80}?)'|"([^"\n]{2,80}?)"|`([^`\n]{2,80}?)`"""
    r"""|“([^”\n]{2,80}?)”|‘([^’\n]{2,80}?)’)(?![\w])"""
)
_DOTTED = re.compile(r"[^\W\d]\w*(?:\.[^\W\d]\w*)*")
_QUERY_WORD = re.compile(r"[^\W_](?:[^\W_]|-)*")
_NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w])")
_CAMEL = re.compile(r"[a-z][A-Z]")


@dataclass(frozen=True)
class Occurrence:
    file: str
    line: int
    text: str  # the whole line, whitespace-normalised
    col: int = 0  # where the match starts in `text`

    def snippet(self, width: int = LINE_CHARS) -> str:
        """The line, or the stretch of it around the match when it is too long."""
        if len(self.text) <= width:
            return self.text
        start = max(0, min(self.col - width // 3, len(self.text) - width))
        piece = self.text[start : start + width]
        return ("…" if start else "") + piece + ("…" if start + width < len(self.text) else "")

    def to_dict(self, width: int = LINE_CHARS) -> dict[str, Any]:
        return {"file": self.file, "line": self.line, "text": self.snippet(width)}


@dataclass
class Evidence:
    text: str
    kind: str  # quoted | phrase | identifier | quantity
    occurrences: list[Occurrence]
    total: int
    weight: float
    files: int = 0
    lines: set[tuple[str, int]] = field(default_factory=set, repr=False)
    scan_complete: bool = True

    @property
    def line_weight(self) -> float:
        """Evidence a single occurrence carries: a literal found in many places says less about
        any one of them than a literal found in two."""
        return float(self.weight * min(1.0, (3 / max(self.total, 1)) ** 0.5))

    @property
    def complete(self) -> bool:
        return self.scan_complete and self.total == len(self.occurrences)

    def to_dict(self, width: int = LINE_CHARS, limit: int | None = None) -> dict[str, Any]:
        shown = self.occurrences if limit is None else self.occurrences[:limit]
        result: dict[str, Any] = {
            "text": self.text,
            "kind": self.kind,
            "total": self.total,
            "complete": self.scan_complete and self.total == len(shown),
            "occurrences": [o.to_dict(width) for o in shown],
        }
        if not self.scan_complete:
            result["scan_limited"] = True
        return result


@dataclass
class EvidenceResult:
    literals: list[Evidence] = field(default_factory=list)
    absent: list[str] = field(default_factory=list)  # code-like names the source never uses
    identifiers: list[str] = field(default_factory=list)  # every code-like name in the request
    limited: bool = False
    scope: tuple[int, int] = (0, 0)  # (code files, text/data files) the exact-match search covered
    unindexed: list[str] = field(
        default_factory=list
    )  # names found only in files Prism does not index

    def hit_lines(self) -> dict[tuple[str, int], float]:
        """Weight of every line that is literal evidence, for scoring code blocks."""
        out: dict[tuple[str, int], float] = {}
        for lit in self.literals:
            for key in lit.lines:
                out[key] = max(out.get(key, 0.0), lit.line_weight)
        return out


def _dedupe(items: list[str]) -> list[str]:
    """Order-preserving unique."""
    return list(dict.fromkeys(items))


def looks_like_code(word: str) -> bool:
    core = word.strip("_")
    if len(core) < 4 or core.lower() in FILLER_WORDS:
        return False
    return "_" in core or bool(_CAMEL.search(core))


def _identifier_candidates(query: str) -> list[str]:
    found: list[str] = []
    for match in _DOTTED.finditer(query):
        word = match.group(0)
        parts = word.split(".")
        if len(parts) > 1 and any(looks_like_code(p) for p in parts):
            found.append(word)
        found.extend(p for p in parts if looks_like_code(p))
    return _dedupe(found)


def _quoted_spans(query: str, context_fields: set[str] | None = None) -> list[str]:
    spans = []
    for match in _QUOTED.finditer(query):
        text = next(g for g in match.groups() if g is not None).strip()
        if match.group(3) is not None and context_fields and text in context_fields:
            continue  # existing fields in an explicit output shape, not literal edit targets
        if len(text) >= 3 and any(c.isalnum() for c in text):
            spans.append(text)
    return _dedupe(spans)


_OLD_BEFORE_WIDE = re.compile(
    r"\b(?:currently|now is|is now|replace|replacing|change|changes|changing|changed)\s+(?:\w+\s+){0,3}$"
)
_CHANGES_TO = re.compile(r"\s*(?:->|→|=>|to)\s*\d")
_TARGET_BEFORE = re.compile(r"\b(?:to|for|become|becomes|be|set|as|into)\s+(?:\w+\s+){0,2}$")
_OLD_BEFORE = re.compile(r"\b(?:instead of|rather than|from|than|currently|was|not|of)\s+$")


def _target_numbers(query: str) -> set[str]:
    """Numbers the request says a value should *become*. When the request also gives the old
    value, only the old one can be found in the source, so these are not searched for."""
    lowered = query.lower()
    roles: list[tuple[str, bool]] = []
    old_values: set[str] = set()
    for match in _NUMBER.finditer(query):
        before = lowered[max(0, match.start() - 28) : match.start()]
        after = lowered[match.end() : match.end() + 14]
        if _OLD_BEFORE.search(before) or _CHANGES_TO.match(after):
            old_values.add(match.group(0))
        roles.append(
            (match.group(0), bool(_TARGET_BEFORE.search(before)) and not _OLD_BEFORE.search(before))
        )
    if not any(not target for _, target in roles):
        return set()  # nothing else to search for; keep what there is
    return {number for number, target in roles if target} - old_values


def _quantities(query: str) -> list[tuple[str, str]]:
    """(number, unit) pairs: every searchable number crossed with every unit the request names,
    so "stay valid for 15 minutes instead of 10" looks for "10 minutes"."""
    skip = _target_numbers(query)
    numbers = [n for n in _NUMBER.findall(query) if n not in skip]
    words = {w.lower() for w in _QUERY_WORD.findall(query)}
    units = sorted(w for w in words if w in QUANTITY_UNITS)
    seen: set[tuple[str, str]] = set()
    pairs = []
    for number in numbers:
        for unit in units:
            if (number, unit) not in seen:
                seen.add((number, unit))
                pairs.append((number, unit))
    return pairs[:6]


def _phrases(query: str) -> list[list[str]]:
    words = _QUERY_WORD.findall(re.sub(r"['’]s\b", "", query))
    out: list[list[str]] = []
    seen: set[str] = set()
    for n in (4, 3, 2):
        for i in range(len(words) - n + 1):
            seg = words[i : i + n]
            low = [w.lower() for w in seg]
            if low[0] in FILLER_WORDS or low[-1] in FILLER_WORDS:
                continue
            if all(w in FILLER_WORDS for w in low):
                continue
            key = " ".join(low)
            if key not in seen:
                seen.add(key)
                out.append(seg)
    return out[:MAX_PHRASE_CANDIDATES]


def _phrase_regex(words: list[str]) -> re.Pattern[str]:
    body = r"[\s_\-]+".join(re.escape(w) for w in words)
    return re.compile(rf"(?<![^\W_]){body}(?![^\W_])", re.IGNORECASE)


def _identifier_regex(name: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(name)}(?!\w)")


def _quantity_regex(number: str, unit: str) -> re.Pattern[str]:
    base = unit[:-1] if unit.endswith("s") and len(unit) > 4 else unit
    word = rf"{re.escape(base)}\w*" if len(base) >= 4 else rf"\b{re.escape(unit)}\b"
    num = rf"(?<![\w.]){re.escape(number)}(?![\w.])"
    return re.compile(rf"{num}\s*-?\s*{word}|{word}[^\n]{{0,48}}?{num}", re.IGNORECASE)


class _Matches(list[Occurrence]):
    """Matching lines plus whether every candidate file was actually searched."""

    def __init__(self) -> None:
        super().__init__()
        self.complete = True


def _scan(
    reader: SourceReader,
    files: set[str],
    pattern: re.Pattern[str],
    is_test: Any,
) -> _Matches:
    # Application code first: a fix belongs in the code, tests and docs come after.
    ordered = sorted(files, key=lambda p: (bool(is_test(p)), p.endswith((".md", ".txt")), p))
    found = _Matches()
    found.complete = len(ordered) <= MAX_FILES_PER_LITERAL
    for path in ordered[:MAX_FILES_PER_LITERAL]:
        lines = reader.lines(path)
        if lines is None:
            found.complete = False
            continue
        for number, line in enumerate(lines, 1):
            target = normalize(
                line
            )  # match canonically; report the line exactly as it is in the file
            match = pattern.search(target)
            if match:
                col = max(0, match.start() - (len(target) - len(target.lstrip())))
                found.append(Occurrence(path, number, line.strip(), col))
                if len(found) >= MAX_OCCURRENCES_SCANNED:
                    found.complete = False
                    return found
    return found


def _literal(
    kind: str, text: str, hits: list[Occurrence], weight: float, limit: int
) -> Evidence | None:
    if not hits:
        return None
    shown = hits[:limit]
    return Evidence(
        text=text,
        kind=kind,
        occurrences=shown,
        total=len(hits),
        weight=weight,
        files=len({h.file for h in hits}),
        lines={(h.file, h.line) for h in hits},
        scan_complete=hits.complete if isinstance(hits, _Matches) else True,
    )


ABSENT_CHECK_SECONDS = 0.35


def _substring_hits(
    index: SourceIndex, reader: SourceReader, name: str, is_test: Any, deadline: float
) -> tuple[_Matches, bool]:
    """Occurrences of `name` anywhere in indexed text, and whether every file was examined."""
    needle = normalize(name)
    paths = sorted(
        [*index.store.manifest.get("files", {}), *index.text.paths],
        key=lambda p: (bool(is_test(p)), p),
    )
    found = _Matches()
    for path in paths:
        if time.monotonic() > deadline:
            found.complete = False
            return found, False
        lines = reader.lines(path)
        if lines is None:
            found.complete = False
            continue
        for number, line in enumerate(lines, 1):
            if needle in normalize(line):
                found.append(Occurrence(path, number, line.strip(), 0))
                if len(found) >= MAX_OCCURRENCES_SCANNED:
                    found.complete = False
                    return found, False
    return found, found.complete


MAX_SKIPPED_READ_BYTES = 8 * 1024 * 1024


def _not_in_skipped_files(store: Any, names: list[str], result: EvidenceResult) -> list[str]:
    """Names that are not in any file Prism skipped for size either.

    A file over `max_file_size` is not indexed, so a name defined only there is invisible to the
    index. It must not be called "new": keep it out of `absent` and mark the result limited."""
    from prism.config import load_config
    from prism.discovery.scanner import discover

    skipped: list[str] = []
    try:
        discover(
            store.root,
            load_config(store.root),
            store.manifest.get("files", {}),
            resniff=False,
            oversize=skipped,
        )
    except OSError:
        result.limited = True
        return []
    if not skipped:
        return names
    remaining = list(names)
    for rel in skipped:
        try:
            with (store.root / rel).open("rb") as fh:
                text = normalize(decode_source(fh.read(MAX_SKIPPED_READ_BYTES)))
        except OSError:
            result.limited = True
            return []
        for name in list(remaining):
            if normalize(name) in text:
                remaining.remove(name)
                result.limited = True
                result.unindexed.append(f"{name} (in {rel}, skipped: larger than max_file_size)")
    return remaining


_GENERIC_REQUEST_WORDS = frozenset(
    ["update", "change", "changes", "changing", "make", "makes", "set", "use", "uses", "using", "app", "apps", "code", "rule", "rules", "value", "values", "need", "needs", "should", "must", "every", "all", "any", "each", "only", "keep", "also", "instead", "now", "new", "old", "current", "currently", "show", "shown", "shows", "user", "users", "text", "message", "messages", "derive", "derived", "implement", "add", "remove", "fix"]
)  # fmt: skip


def _context_tokens(query: str) -> set[str]:
    """What the request is about, as stemmed words (no filler, numbers or generic verbs)."""
    out = set()
    for tok in tokenize(normalize(query)):
        if tok.isdigit() or tok in FILLER_WORDS or tok in _GENERIC_REQUEST_WORDS or len(tok) < 3:
            continue
        out.add(tok)
    return out


def _changed_numbers(query: str) -> list[str]:
    """Numbers of two or more digits that the request wants changed away from (the old value)."""
    skip = _target_numbers(query)
    lowered = query.lower()
    found = []
    for match in _NUMBER.finditer(query):
        number = match.group(0)
        if number in skip or len(number) < 2 or "." in number:
            continue
        before = lowered[max(0, match.start() - 24) : match.start()]
        after = lowered[match.end() : match.end() + 14]
        # Only a number the request says is being replaced is "the old value": a limit such as
        # "above 100 percent" or "at most 5 items" is a condition, not a literal to hunt for.
        if (
            _OLD_BEFORE.search(before)
            or _OLD_BEFORE_WIDE.search(before)
            or _CHANGES_TO.match(after)
        ):
            found.append(number)
    return _dedupe(found)[:3]


def _number_hits(
    index: SourceIndex, reader: SourceReader, number: str, context: set[str], is_test: Any
) -> _Matches:
    """Standalone occurrences of `number` in files that also talk about what the request is about.

    A line counts when it shares a word with the request; every other line of a file that has at
    least one such line counts too (a sibling statement such as `year - 23` belongs with the
    message `at least 23 years`). Files with no on-topic line are noise (ports, sizes) and skipped."""
    pattern = re.compile(rf"(?<![\w.]){re.escape(number)}(?![\w]|\.\d)")
    roots = {tok[:5] for tok in context}  # stems share a prefix with the words that produced them
    found = _Matches()
    paths = sorted(index.files_with_all_text([number]), key=lambda p: (bool(is_test(p)), p))
    found.complete = len(paths) <= MAX_FILES_PER_LITERAL * 2
    for path in paths[: MAX_FILES_PER_LITERAL * 2]:
        lines = reader.lines(path)
        if lines is None:
            found.complete = False
            continue
        rows = [(n, line) for n, line in enumerate(lines, 1) if pattern.search(normalize(line))]
        if not rows:
            continue
        on_topic = [any(root in normalize(line).lower() for root in roots) for _, line in rows]
        if not any(on_topic):
            continue
        for (n, line), _ in zip(rows, on_topic, strict=True):
            found.append(Occurrence(path, n, line.strip(), 0))
            if len(found) >= MAX_OCCURRENCES_SCANNED:
                found.complete = False
                return found
    return found


def find_literals(
    index: SourceIndex,
    reader: SourceReader,
    query: str,
    per_literal: int = 24,
    context_fields: set[str] | None = None,
) -> EvidenceResult:
    """Everything in the request that can be matched exactly, and where it occurs."""
    original_query = query
    query = normalize(query)
    reader.corpus = index.text
    result_scope = (len(index.store.manifest.get("files", {})), len(index.text.paths))
    result = EvidenceResult()
    result.scope = result_scope
    is_test = index.store._is_test
    found: list[Evidence] = []
    quoted_words: set[str] = set()

    def scan_matches(files: set[str], pattern: re.Pattern[str]) -> _Matches:
        matches = _scan(reader, files, pattern, is_test)
        result.limited |= not matches.complete
        return matches

    for text in _quoted_spans(query, context_fields):
        words = _QUERY_WORD.findall(text)
        if not words:
            continue
        quoted_words.add(text.lower())
        tokens = tokenize(text)
        if any(index.df_text(t) == 0 for t in tokens):
            continue
        files = index.files_with_all_text(tokens)
        if not files:
            continue
        pattern = (
            _identifier_regex(text)
            if len(words) == 1 and looks_like_code(text)
            else _phrase_regex(words)
        )
        lit = _literal("quoted", text, scan_matches(files, pattern), 9.0, per_literal)
        if lit and lit.total <= MAX_NAMED_LINES:
            found.append(lit)

    for name in _identifier_candidates(query):
        result.identifiers.append(name)
        tokens = tokenize(name)
        files = (
            index.files_with_all_text(tokens)
            if tokens and all(index.df_text(t) for t in tokens)
            else set()
        )
        hits = scan_matches(files, _identifier_regex(name)) if files else _Matches()
        standalone = re.search(rf"(?<![\w.]){re.escape(name)}(?![\w.])", query) is not None
        lit = _literal("identifier", name, hits, 7.0 if standalone else 4.0, per_literal)
        if lit is None:
            if "." not in name and hits.complete:
                result.absent.append(name)
        elif lit.total <= MAX_NAMED_LINES:
            found.append(lit)

    if result.absent:
        # "Not in the source" is a strong claim that tells the agent to skip searching. The word
        # index only knows whole words, so a name glued into a longer string (or one whose words
        # were never indexed) would be reported missing. Prove it by looking at the text itself.
        still_absent: list[str] = []
        deadline = time.monotonic() + ABSENT_CHECK_SECONDS
        for name in result.absent:
            hits, complete = _substring_hits(index, reader, name, is_test, deadline)
            lit = _literal("identifier", name, hits, 4.0, per_literal) if hits else None
            if lit is not None and lit.total <= MAX_NAMED_LINES:
                found.append(lit)
            elif complete and not hits:
                still_absent.append(name)
            elif not complete:
                result.limited = True  # could not prove the name is new: say so, do not claim it
        if still_absent:
            still_absent = _not_in_skipped_files(index.store, still_absent, result)
        result.absent = still_absent

    for number, unit in _quantities(query):
        tokens = [number, stem(unit)]
        if any(index.df_text(t) == 0 for t in tokens):
            continue
        files = index.files_with_all_text(tokens)
        hits = scan_matches(files, _quantity_regex(number, unit)) if files else _Matches()
        lit = _literal("quantity", f"{number} {unit}", hits, 8.0, per_literal)
        if lit and lit.total <= MAX_NAMED_LINES:
            found.append(lit)

    # A bare changed number ("from 23 to 25"): the old value is the thing to find, wherever the
    # source states it, not only next to a unit word.
    unit_numbers = {n for n, _ in _quantities(query)}
    context = _context_tokens(query)
    for number in _changed_numbers(query):
        if number in unit_numbers or index.df_text(number) == 0:
            continue
        hits = _number_hits(index, reader, number, context, is_test)
        result.limited |= not hits.complete
        lit = _literal("number", f"{number} (current value)", hits, 7.5, per_literal)
        if lit and lit.total <= MAX_NAMED_LINES:
            found.append(lit)

    phrases: list[Evidence] = []
    skip_numbers = _target_numbers(query)
    for words in _phrases(query):
        if skip_numbers and any(w in skip_numbers for w in words):
            continue
        text = " ".join(words)
        if text.lower() in quoted_words:
            continue
        if len(words) < 3 and not any(any(c.isdigit() for c in w) for w in words):
            continue  # two plain words match generic prose, not evidence
        tokens = tokenize(text)
        if not tokens or any(index.df_text(t) == 0 for t in tokens):
            continue
        files = index.files_with_all_text(tokens)
        if not files or len(files) > MAX_FILES_PER_LITERAL // 2:
            continue
        hits = scan_matches(files, _phrase_regex(words))
        lit = _literal("phrase", text, hits, 5.0 + len(words), per_literal)
        if lit and lit.total <= MAX_PHRASE_LINES:
            phrases.append(lit)
    # Keep the longest phrases; a shorter one that only repeats their lines adds nothing.
    phrases.sort(key=lambda p: (-len(p.text.split()), p.total, p.text))
    covered: set[tuple[str, int]] = set()
    for lit in phrases:
        if lit.lines <= covered:
            continue
        covered |= lit.lines
        found.append(lit)

    found = [
        lit
        for lit in found
        if not (lit.kind == "phrase" and any(lit.lines < other.lines for other in found))
    ]
    # Strongest first; a literal that only repeats lines already reported adds nothing, except
    # strings and names the user typed themselves, which always stay.
    found.sort(key=lambda lit: (-lit.weight, -len(lit.lines), lit.text))
    kept: list[Evidence] = []
    seen_lines: set[tuple[str, int]] = set()
    for lit in found:
        if lit.lines <= seen_lines and lit.kind not in (
            "quoted",
            "identifier",
            "number",
            "quantity",
        ):
            continue
        seen_lines |= lit.lines
        kept.append(lit)
    if original_query != query:
        # Matching is canonical (NFC); report each literal in the spelling the user typed.
        spelled = {normalize(t): t for t in _quoted_spans(original_query, context_fields)}
        spelled.update({normalize(n): n for n in _identifier_candidates(original_query)})
        kept = [replace(lit, text=spelled.get(lit.text, lit.text)) for lit in kept]
    result.literals = kept[:MAX_LITERALS]
    return result
