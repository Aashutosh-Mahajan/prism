"""Money arithmetic."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Money:
    """An amount in cents."""

    cents: int

    def __add__(self, other: "Money") -> "Money":
        return Money(self.cents + other.cents)

    def scale(self, factor: float) -> "Money":
        """Multiply by a factor, rounding half up."""
        return Money(int(self.cents * factor + 0.5))


def zero() -> Money:
    return Money(0)
