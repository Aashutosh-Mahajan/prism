"""Small helpers."""

import json
from typing import Any


def to_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True)


def chunk(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)]
