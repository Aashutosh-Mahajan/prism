"""Helpers."""


def tag(entry: dict[str, object], tags: list[str] = []) -> list[str]:
    """Return the tags for an entry, adding the default tag."""
    tags.append(str(entry.get("kind", "misc")))
    return tags


def cents(amount: float) -> int:
    return int(round(amount * 100))
