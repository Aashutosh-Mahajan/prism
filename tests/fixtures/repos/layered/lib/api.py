"""Public facade: fluent validators for a single field."""

from lib import rules


class Field:
    def __init__(self) -> None:
        self._checks: list[object] = []

    def _add(self, check: object) -> "Field":
        self._checks.append(check)
        return self

    def min_length(self, n: int) -> "Field":
        return self._add(rules.min_length(n))

    def max_length(self, n: int) -> "Field":
        return self._add(rules.max_length(n))

    def round_to(self, places: int) -> "Field":
        return self._add(rules.round_to(places))

    def validate(self, value: object) -> list[str]:
        problems: list[str] = []
        for check in self._checks:
            problems.extend(check.run(value))  # type: ignore[attr-defined]
        return problems
