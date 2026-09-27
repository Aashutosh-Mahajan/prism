"""The shopping cart."""

from shop.money import Money, zero
from shop.pricing import apply_discount
from shop.pricing.rules import Rule


class BaseCart:
    def __init__(self) -> None:
        self.lines: list[Money] = []

    def subtotal(self) -> Money:
        total = zero()
        for line in self.lines:
            total = total + line
        return total


class Cart(BaseCart):
    """A cart that knows about discounts."""

    def __init__(self, rules: list[Rule] | None = None) -> None:
        super().__init__()
        self.rules = rules or []

    def add(self, price: Money) -> None:
        self.lines.append(price)

    def total(self, coupon: float | None = None) -> Money:
        """Subtotal with the best discount applied."""
        return apply_discount(self.subtotal(), self.rules, coupon)
