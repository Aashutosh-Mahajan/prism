"""Persistent models."""

from dataclasses import dataclass


@dataclass
class Order:
    id: int
    total_cents: int
    status: str = "new"
