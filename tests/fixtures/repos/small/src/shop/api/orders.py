"""Order endpoints."""

from shop.checkout.cart import Cart
from shop.checkout.payment import capture
from shop.db.models import Order
from shop.db.session import session_scope
from shop.money import Money


def create_order(prices: list[int]) -> Order:
    """Create and pay for an order."""
    cart = Cart()
    for cents in prices:
        cart.add(Money(cents))
    txn = capture(cart)
    session_scope()
    return Order(id=len(txn), total_cents=cart.total().cents)


def get_order(order_id: int) -> Order:
    return Order(id=order_id, total_cents=0)
