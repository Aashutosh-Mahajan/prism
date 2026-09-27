from shop.api.orders import create_order


def test_create_order() -> None:
    assert create_order([100]).total_cents == 100
