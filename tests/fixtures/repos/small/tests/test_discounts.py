from shop.money import Money
from shop.pricing import apply_discount
from shop.pricing.rules import Rule


def test_best_rule_wins() -> None:
    rules = [Rule(0.1, Money(0)), Rule(0.2, Money(1000))]
    assert apply_discount(Money(2000), rules).cents == 1600
