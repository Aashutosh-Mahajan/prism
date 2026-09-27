"""Config keys and environment variables -> where they are read."""

from __future__ import annotations

from prism.core.models import ConfigKey, ConfigRead
from prism.extractors.base import Extractor, ExtractorContext


class ConfigExtractor(Extractor[list[ConfigKey]]):
    name = "config"

    def run(self, ctx: ExtractorContext) -> list[ConfigKey]:
        keys: dict[tuple[str, str], set[ConfigRead]] = {}
        for mod, pf in ctx.table.files.items():
            for read in pf.module_env_reads:
                keys.setdefault((read.key, read.kind), set()).add(
                    ConfigRead(None, pf.path, read.line)
                )
            for ps in pf.symbols:
                for read in ps.env_reads:
                    keys.setdefault((read.key, read.kind), set()).add(
                        ConfigRead(f"{mod}.{ps.qualname}", pf.path, read.line)
                    )
        return [
            ConfigKey(key, kind, sorted(reads, key=lambda r: (r.file, r.line, r.symbol or "")))
            for (key, kind), reads in sorted(keys.items())
        ]
