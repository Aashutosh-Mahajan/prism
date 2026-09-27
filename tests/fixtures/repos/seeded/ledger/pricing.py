"""Price calculation."""


def sale_price(price: float, sale_rate: float) -> float:
    return price * (1 - sale_rate)


def apply_discount(price: float, sale_rate: float, coupon_rate: float) -> float:
    """Apply the sale, then the coupon on top of the sale price."""
    sale = sale_price(price, sale_rate)
    coupon_saving = price * coupon_rate
    return sale - coupon_saving
