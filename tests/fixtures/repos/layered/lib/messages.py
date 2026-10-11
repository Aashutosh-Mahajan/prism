"""User-facing texts."""


def too_short(n: int) -> str:
    return f"must have at least {n} characters"


def too_long(n: int) -> str:
    return f"must have at most {n} characters"


def not_rounded(places: int) -> str:
    return f"must be rounded to {places} decimal places"
