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
    return first if len(re.findall(r"[A-Za-z0-9_]+", first)) >= 4 else text
