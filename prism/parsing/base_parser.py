"""Parser interface and registry. One parser per language."""

from __future__ import annotations

from abc import ABC, abstractmethod

from prism.core.models import ParsedFile


class BaseParser(ABC):
    language: str

    @abstractmethod
    def parse(self, path: str, source: bytes, module: str, is_package: bool) -> ParsedFile:
        """Parse one file. Must never raise on bad input; set `parse_error` instead."""


_REGISTRY: dict[str, BaseParser] = {}


def register_parser(parser: BaseParser) -> None:
    _REGISTRY[parser.language] = parser


def get_parser(language: str) -> BaseParser | None:
    if not _REGISTRY:
        from prism.parsing.python_ast import PythonAstParser

        register_parser(PythonAstParser())
        # Optional extra: `pip install prism-ctx[treesitter]` adds JS/TS/Go/Java.
        from prism.parsing import treesitter

        if treesitter.available():
            for parser in treesitter.parsers():
                register_parser(parser)
    return _REGISTRY.get(language)
