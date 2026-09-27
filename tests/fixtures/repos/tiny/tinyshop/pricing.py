"""Discount rules and application."""


def eligible_rules(total: float, coupon: str | None) -> list[float]:
    """Return the discount rates that apply to this total."""
    rules = []
    if coupon == "SAVE10":
        rules.append(0.10)
    if total > 100:
        rules.append(0.05)
    return rules


def apply_discount(total: float, coupon: str | None = None) -> float:
    """Apply the best eligible discount to a total."""
    rates = eligible_rules(total, coupon)
    if not rates:
        return total
    return round(total * (1 - max(rates)), 2)


def _debug_rates() -> None:
    print(eligible_rules(200.0, "SAVE10"))
