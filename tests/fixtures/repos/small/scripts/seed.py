#!/usr/bin/env python
"""Seed the database with demo orders."""

from shop.api.orders import create_order


def main() -> None:
    for i in range(3):
        create_order([100 * (i + 1)])


main()
