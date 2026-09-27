from ledger.pricing import apply_discount


def test_coupon_applies_to_sale_price() -> None:
    # 100 -> sale 10% -> 90 -> coupon 10% of the sale price -> 81
    assert apply_discount(100.0, 0.1, 0.1) == 81.0
