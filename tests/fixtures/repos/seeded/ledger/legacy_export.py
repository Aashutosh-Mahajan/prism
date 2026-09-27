"""Old export format (kept for reference)."""


def _old_format(entries: list[float]) -> str:
    return ";".join(str(e) for e in entries)
