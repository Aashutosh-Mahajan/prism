"""Applying discounts to carts."""

from shop.money import Money

from . import rules as rules_mod


def apply_discount(amount: Money, rules: list["rules_mod.Rule"], coupon: float | None = None) -> Money:
    """Apply the best eligible discount to an amount."""
    eligible = rules_mod.eligible_rules(amount, rules)
    best = max((r.rate for r in eligible), default=0.0)
    if coupon:
        best = max(best, coupon)
    return amount.scale(1 - best)
