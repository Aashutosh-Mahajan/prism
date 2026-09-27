"""Extractor interface and registry.

An extractor derives facts from the symbol table and graphs. New extractors
subclass `Extractor`, set a unique `name`, and call `register_extractor`;
the pipeline does not need to change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, TypeVar

from prism.config import PrismConfig
from prism.core.models import CallGraph, ImportGraph
from prism.graph.symbol_table import SymbolTable

T = TypeVar("T")


@dataclass(frozen=True)
class ExtractorContext:
    root: Path
    config: PrismConfig
    table: SymbolTable
    import_graph: ImportGraph
    call_graph: CallGraph
    pyproject: dict[str, Any]


class Extractor(ABC, Generic[T]):
    name: str

    @abstractmethod
    def run(self, ctx: ExtractorContext) -> T: ...


_REGISTRY: dict[str, Extractor[Any]] = {}


def register_extractor(extractor: Extractor[Any]) -> None:
    if extractor.name in _REGISTRY:
        raise ValueError(f"extractor '{extractor.name}' already registered")
    _REGISTRY[extractor.name] = extractor


def registered_extractors() -> list[Extractor[Any]]:
    return [_REGISTRY[k] for k in sorted(_REGISTRY)]
