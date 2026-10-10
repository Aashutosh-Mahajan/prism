"""Exact-match search over the text and data files Prism does not parse.

Translations, config, docs, templates and languages without a parser (`.json`, `.yaml`, `.md`,
`.html`, `.po`, `.dart`, ...) carry the same literals as code: a message shown to users usually
also lives in five locale files. If literal lists covered only parsed code, an agent could never
trust them and would grep the whole repository anyway. This corpus is used only for literal and
old-value lookups. It adds no symbols and never takes part in ranking code blocks.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any

from prism.config import load_config
from prism.core.textio import decode_source, normalize
from prism.navigator.cache_db import cache_dir
from prism.navigator.text import tokenize

TEXT_DB = "text-v1.sqlite"
MAX_TEXT_BYTES = 256 * 1024
MAX_TEXT_FILES = 4000
TEXT_EXTENSIONS = frozenset(
    [".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".properties", ".md", ".markdown", ".rst", ".txt", ".html", ".htm", ".xml", ".css", ".scss", ".less", ".po", ".pot", ".csv", ".tsv", ".dart", ".vue", ".svelte", ".gradle", ".tf", ".env.example", ".proto", ".graphql", ".gql"]
)  # fmt: skip
SKIP_NAMES = frozenset(
    ["package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "pipfile.lock", "composer.lock", "cargo.lock", "gemfile.lock", "go.sum", "npm-shrinkwrap.json"]
)  # fmt: skip


def is_text_candidate(path: str, size: int) -> bool:
    name = path.rsplit("/", 1)[-1].lower()
    if name in SKIP_NAMES or (name.startswith(".env") and not name.endswith(".example")):
        return False
    if name.endswith((".min.js", ".min.css", ".map")) or size > MAX_TEXT_BYTES or size == 0:
        return False
    dot = name.rfind(".")
    return dot >= 0 and name[dot:] in TEXT_EXTENSIONS


class TextCorpus:
    """A synchronized postings table of text files, keyed by (size, mtime) with a content hash."""

    def __init__(self, root: Path, manifest: dict[str, Any]) -> None:
        self.root = root
        self._manifest_files = set(manifest.get("files", {}))
        directory = cache_dir(root)
        directory.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(directory / TEXT_DB, timeout=30)
        self._paths: dict[str, set[str]] = {}
        self._sha: dict[str, str] = {}
        self.truncated = False
        try:
            self._sync()
        except BaseException:
            self._conn.close()
            raise

    def close(self) -> None:
        self._conn.close()

    def _listing(self) -> dict[str, tuple[int, int]]:
        from prism.discovery.scanner import discover, recent_text_listing

        found = recent_text_listing(self.root)
        if found is None:
            found = []
            discover(self.root, load_config(self.root), None, resniff=False, text_files=found)
        listing = {p: (size, mtime) for p, size, mtime in found if p not in self._manifest_files}
        if len(listing) > MAX_TEXT_FILES:
            self.truncated = True
            listing = dict(sorted(listing.items())[:MAX_TEXT_FILES])
        return listing

    def _sync(self) -> None:
        conn = self._conn
        conn.executescript(
            "CREATE TABLE IF NOT EXISTS tfiles (path TEXT PRIMARY KEY, size INTEGER, mtime INTEGER, sha TEXT);"
            "CREATE TABLE IF NOT EXISTS tpostings (term TEXT, path TEXT);"
            "CREATE INDEX IF NOT EXISTS t_term ON tpostings(term);"
            "CREATE INDEX IF NOT EXISTS t_path ON tpostings(path);"
        )
        conn.execute("BEGIN IMMEDIATE")
        cached = {
            p: (s, m, h) for p, s, m, h in conn.execute("SELECT path,size,mtime,sha FROM tfiles")
        }
        listing = self._listing()
        for path in sorted(set(cached) - set(listing)):
            conn.execute("DELETE FROM tpostings WHERE path=?", (path,))
            conn.execute("DELETE FROM tfiles WHERE path=?", (path,))
        for path, (size, mtime) in sorted(listing.items()):
            old = cached.get(path)
            if old and old[0] == size and old[1] == mtime:
                self._sha[path] = old[2]
                continue
            try:
                raw = (self.root / path).read_bytes()
            except OSError:
                continue
            if b"\x00" in raw[:8192]:
                continue
            sha = hashlib.sha256(raw).hexdigest()
            self._sha[path] = sha
            conn.execute("DELETE FROM tpostings WHERE path=?", (path,))
            terms = sorted(set(tokenize(normalize(decode_source(raw)))))
            conn.execute("INSERT OR REPLACE INTO tfiles VALUES (?,?,?,?)", (path, size, mtime, sha))
            conn.executemany("INSERT INTO tpostings VALUES (?,?)", [(t, path) for t in terms])
        conn.commit()

    @property
    def paths(self) -> list[str]:
        return sorted(self._sha)

    @property
    def paths_set(self) -> set[str]:
        return set(self._sha)

    def paths_with(self, term: str) -> set[str]:
        found = self._paths.get(term)
        if found is None:
            found = {
                r[0] for r in self._conn.execute("SELECT path FROM tpostings WHERE term=?", (term,))
            }
            self._paths[term] = found
        return found

    def files_with_all(self, terms: list[str]) -> set[str]:
        if not terms:
            return set()
        found: set[str] | None = None
        for term in sorted(set(terms), key=lambda t: len(self.paths_with(t))):
            found = set(self.paths_with(term)) if found is None else found & self.paths_with(term)
            if not found:
                break
        return found or set()

    def df(self, term: str) -> int:
        return len(self.paths_with(term))

    def lines(self, path: str) -> list[str] | None:
        """Lines of a corpus file, only if it still has the content that was indexed."""
        sha = self._sha.get(path)
        if sha is None:
            return None
        try:
            raw = (self.root / path).read_bytes()
        except OSError:
            return None
        if hashlib.sha256(raw).hexdigest() != sha:
            return None
        from prism.navigator.source_index import split_lines

        return split_lines(decode_source(raw))
