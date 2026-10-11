"""Check implementations: where the behaviour actually lives."""

from decimal import Decimal

from lib import messages


class MinLengthCheck:
    def __init__(self, n: int) -> None:
        self.n = n

    def run(self, value: str) -> list[str]:
        size = len(value.encode("utf-16-le")) // 2
        if size >= self.n:
            return []
        return [messages.too_short(self.n)]


class MaxLengthCheck:
    def __init__(self, n: int) -> None:
        self.n = n

    def run(self, value: str) -> list[str]:
        if len(value) <= self.n:
            return []
        return [messages.too_long(self.n)]


class RoundCheck:
    def __init__(self, places: int) -> None:
        self.places = places

    def run(self, value: float) -> list[str]:
        exact = Decimal(value)
        rounded = round(exact, self.places)
        if rounded == exact:
            return []
        return [messages.not_rounded(self.places)]
