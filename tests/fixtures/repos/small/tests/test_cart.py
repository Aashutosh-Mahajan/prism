from shop.checkout.cart import Cart
from shop.money import Money


def test_total() -> None:
    cart = Cart()
    cart.add(Money(500))
    assert cart.total().cents == 500
