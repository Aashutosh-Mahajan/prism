"""Discount rules."""

from ..money import Money

__all__ = ["Rule", "eligible_rules"]


class Rule:
    """A percentage discount with a minimum spend."""

    def __init__(self, rate: float, minimum: Money) -> None:
        self.rate = rate
        self.minimum = minimum

    def applies(self, amount: Money) -> bool:
        return amount.cents >= self.minimum.cents


def eligible_rules(amount: Money, rules: list[Rule]) -> list[Rule]:
    """Rules whose minimum spend is met."""
    return [r for r in rules if r.applies(amount)]
