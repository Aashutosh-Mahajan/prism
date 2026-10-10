"""Separate an edit's leading operation from its acceptance criteria.

All text remains searchable. The leading request only supplies a ranking prior;
URLs, qualified identifiers and later literal requirements are never discarded.
"""

from __future__ import annotations

import re

from prism.navigator.text import tokenize

_EDIT = re.compile(
    r"^\s*(?:please\s+)?(?:fix|change|update|add|remove|implement|repair|refactor|rename)\b", re.I
)
_BOUNDARY = re.compile(r"[.!?]\s+(?=[A-Z])|\n\s*\n")
_REQUIREMENT = re.compile(r"\s+(?:should|must|needs?\s+to)\b", re.I)
_OPERATION_GROUPS = (
    ("extract", "extraction", "parse", "parser", "parsing"),
    ("sort", "sorting", "rank", "ranking", "ordering", "order"),
    ("detect", "detection", "contains"),
    ("mask", "masking", "sanitize", "redact"),
)

_ADDITIVE = re.compile(
    r"\b(?:add|extend|introduce|also|new|additional)\b"
    r"|\b(?:should|must|needs?\s+to)\s+(?:serialize|serialise|accept|support|handle|allow)\b",
    re.I,
)
_NEW_ARGUMENT = re.compile(
    r"\b(?:serialize|serialise|accept|support|handle|allow)\s+"
    r"(?:(?:for|also|the|type|objects?\s+of\s+type)\s+)*[`\"']?"
    r"(?P<name>[^\W\d]\w*(?:\.[^\W\d]\w*)*)",
    re.I,
)


def introduced_identifiers(query: str) -> set[str]:
    """Type arguments introduced by an explicit feature addition, not edit locations.

    Keep this conservative: ordinary lookups and bug fixes retain exact identifier
    ranking. The caller still reports all literal occurrences; only their ranking
    role changes. Qualified names and their final component represent one argument.
    """
    if not _ADDITIVE.search(query):
        return set()
    result: set[str] = set()
    for match in _NEW_ARGUMENT.finditer(query):
        name = match["name"]
        if "." in name or "_" in name or re.search(r"[a-z][A-Z]", name):
            result.update((name, name.rsplit(".", 1)[-1]))
    return result


def request_operations(query: str) -> set[str]:
    """Name-level operation evidence, independent of later error examples."""
    terms = set(tokenize(request_focus(query)))
    return set().union(
        *(
            set(tokenize(" ".join(group)))
            for group in _OPERATION_GROUPS
            if terms & set(tokenize(" ".join(group)))
        )
    )


def request_focus(query: str) -> str:
    """Prefer the requested change over lengthy examples and rejection rules."""
    text = query.strip()
    if not _EDIT.match(text) and not _REQUIREMENT.search(text):
        return text
    first = _BOUNDARY.split(text, maxsplit=1)[0]
    # Noun-first requests name the existing behavior before describing a new
    # field or its edge cases. Those requirements remain literal/search evidence,
    # but cannot outrank the object that actually needs changing.
    # Keep the first requirement: it contains the operation and existing shape.
    # Only later acceptance sentences receive the weaker ranking prior.
    # "Fix the parser used by checkout" names the parser as the target;
    # checkout is a caller hint, not another equally weighted edit target.
    first = re.split(r"\s+used\s+(?:by|for)\s+", first, maxsplit=1, flags=re.I)[0]
    return first if len(re.findall(r"\w+", first)) >= 4 else text
