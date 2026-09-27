"""API application entry point."""

from shop.api import orders
from shop.utils import to_json


def handle(path: str) -> str:
    if path == "/orders":
        return to_json(orders.create_order([100, 250]).__dict__)
    return to_json({"error": "not found"})


def run() -> None:
    print(handle("/orders"))


if __name__ == "__main__":
    run()
