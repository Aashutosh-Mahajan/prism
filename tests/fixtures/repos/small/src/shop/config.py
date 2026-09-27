"""Settings read from the environment."""

import os

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///shop.db")


def get_setting(name: str, default: str = "") -> str:
    return os.environ.get(name, default)
