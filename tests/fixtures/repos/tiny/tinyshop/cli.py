"""Command-line entry point."""

import sys

from tinyshop.cart import Cart


def main(argv: list[str] | None = None) -> int:
    cart = Cart()
    for arg in argv if argv is not None else sys.argv[1:]:
        cart.add(float(arg))
    print(cart.total())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
