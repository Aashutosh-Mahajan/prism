from lib import Field


def test_min_length_rejects_short_value() -> None:
    assert Field().min_length(3).validate("ab")


def test_max_length_rejects_long_value() -> None:
    assert Field().max_length(2).validate("abc")


def test_round_to_accepts_rounded_value() -> None:
    assert not Field().round_to(2).validate(2.5)
