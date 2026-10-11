"""Rule constructors used by the facade."""

from lib import checks


def min_length(n: int) -> checks.MinLengthCheck:
    return checks.MinLengthCheck(n)


def max_length(n: int) -> checks.MaxLengthCheck:
    return checks.MaxLengthCheck(n)


def round_to(places: int) -> checks.RoundCheck:
    return checks.RoundCheck(places)
