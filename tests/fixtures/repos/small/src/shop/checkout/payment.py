"""Payment capture."""

from shop.checkout.cart import Cart
from shop.config import get_setting


class PaymentError(Exception):
    pass


def capture(cart: Cart) -> str:
    """Capture payment for a cart. Returns a transaction id."""
    provider = get_setting("PAYMENT_PROVIDER", "fake")
    amount = cart.total()
    if amount.cents <= 0:
        raise PaymentError("nothing to charge")
    return f"{provider}-{amount.cents}"
