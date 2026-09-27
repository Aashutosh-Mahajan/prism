"""Shopping cart."""

from tinyshop import pricing


class Cart:
    """A list of priced items."""

    def __init__(self) -> None:
        self.items: list[float] = []

    def add(self, price: float) -> None:
        self.items.append(price)

    def subtotal(self) -> float:
        return sum(self.items)

    def total(self, coupon: str | None = None) -> float:
        """Subtotal with discounts applied."""
        return pricing.apply_discount(self.subtotal(), coupon)
