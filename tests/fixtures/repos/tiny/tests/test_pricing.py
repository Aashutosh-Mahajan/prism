from tinyshop.cart import Cart
from tinyshop.pricing import apply_discount


def test_coupon() -> None:
    assert apply_discount(50.0, "SAVE10") == 45.0


def test_cart_total() -> None:
    cart = Cart()
    cart.add(50.0)
    assert cart.total() == 50.0
