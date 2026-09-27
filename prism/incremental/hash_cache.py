"""Parse cache and incremental state in `.aicontext/cache/state.sqlite` (gitignored).

- `parsed`: one serialized `ParsedFile` per path, valid while its SHA-256 and
  the parser version match. Unchanged files are never re-parsed.
- `state`: small JSON blobs carried between runs (previous edges and ranks
  for lazy PageRank, git intelligence, the structural snapshot for drift).

JSON only (no pickle): the cache directory lives inside the user's repo.
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
from pathlib import Path
from typing import Any

from prism import __version__
from prism.core.models import (
    CallRef,
    EnvRead,
    ImportRef,
    ParsedFile,
    ParsedSymbol,
    Smell,
    UrlPattern,
)
from prism.core.paths import AICONTEXT

PARSER_VERSION = f"{__version__}+5"


def _encode(pf: ParsedFile) -> str:
    return json.dumps(dataclasses.asdict(pf), separators=(",", ":"))


def _decode(text: str) -> ParsedFile:
    d: dict[str, Any] = json.loads(text)
    symbols = []
    for s in d.pop("symbols"):
        s["lines"] = tuple(s["lines"])
        s["calls"] = [CallRef(**c) for c in s["calls"]]
        s["env_reads"] = [EnvRead(**e) for e in s["env_reads"]]
        s["fields"] = [tuple(f) for f in s["fields"]]
        symbols.append(ParsedSymbol(**s))
    return ParsedFile(
        symbols=symbols,
        imports=[ImportRef(**i) for i in d.pop("imports")],
        module_calls=[CallRef(**c) for c in d.pop("module_calls")],
        module_env_reads=[EnvRead(**e) for e in d.pop("module_env_reads")],
        url_patterns=[UrlPattern(**u) for u in d.pop("url_patterns")],
        smells=[Smell(**s) for s in d.pop("smells")],
        **d,
    )


class StateCache:
    def __init__(self, root: Path) -> None:
        path = root / AICONTEXT / "cache" / "state.sqlite"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS parsed (path TEXT PRIMARY KEY, sha TEXT, version TEXT, data TEXT)"
        )
        self.conn.execute("CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT)")

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()

    def __enter__(self) -> StateCache:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- parse cache ---------------------------------------------------------

    def cached_parses(self, wanted: dict[str, str]) -> dict[str, ParsedFile]:
        """Cached `ParsedFile`s for paths whose SHA matches `wanted[path]`."""
        out: dict[str, ParsedFile] = {}
        for path, sha, version, data in self.conn.execute(
            "SELECT path, sha, version, data FROM parsed"
        ):
            if wanted.get(path) == sha and version == PARSER_VERSION:
                try:
                    out[path] = _decode(data)
                except (ValueError, TypeError, KeyError):
                    continue
        return out

    def store_parses(
        self, parsed: list[ParsedFile], shas: dict[str, str], only: set[str] | None = None
    ) -> None:
        """Store parses (only the paths in `only`, if given) and drop entries for deleted files."""
        keep = set(shas)
        self.conn.executemany(
            "INSERT OR REPLACE INTO parsed VALUES (?,?,?,?)",
            [
                (pf.path, shas[pf.path], PARSER_VERSION, _encode(pf))
                for pf in parsed
                if pf.path in shas and (only is None or pf.path in only)
            ],
        )
        stale = [p for (p,) in self.conn.execute("SELECT path FROM parsed") if p not in keep]
        self.conn.executemany("DELETE FROM parsed WHERE path = ?", [(p,) for p in stale])

    # --- state ---------------------------------------------------------------

    def get(self, key: str) -> Any:
        row = self.conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, value: Any) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO state VALUES (?, ?)", (key, json.dumps(value, sort_keys=True))
        )
