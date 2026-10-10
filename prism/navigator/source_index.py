"""Persistent body search. Synchronize changed manifest hashes, never rescan on a query.

`SourceIndex` is a synchronized view of the BM25 postings in `source-v2.sqlite`; the postings
are what let a query find every file containing some words without opening any file.
`SourceReader` returns verified source lines: text is only exposed when it still matches the
hash recorded in the manifest, so a stale edit can never leak into an answer.
"""

from __future__ import annotations

import hashlib
import math
import re
import sqlite3
from pathlib import Path
from types import TracebackType
from typing import Any

from prism.core.textio import decode_source
from prism.navigator.cache_db import cache_dir
from prism.navigator.store import IndexStore
from prism.navigator.text import bm25, term_counts, tokenize

SOURCE_DB = "source-v3.sqlite"  # v3: Unicode-aware postings (v2 dropped non-ASCII words)
MAX_LINE_CHARS = 400


def read_indexed_source(store: IndexStore, file: str) -> str | None:
    """Only expose source matching the indexed revision and inside this repository."""
    expected = store.manifest.get("files", {}).get(file, {}).get("sha256")
    path = (store.root / file).resolve()
    if not expected or not path.is_relative_to(store.root):
        return None
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if hashlib.sha256(raw).hexdigest() != expected:
        return None
    return decode_source(raw)


_PY_NEWLINE = re.compile(r"\r\n|\r|\n")


def split_lines(text: str, python: bool = False) -> list[str]:
    """Lines numbered the way the parsers number them, without a phantom last line.

    Python's tokenizer ends a line at a newline, CRLF or a lone CR; the tree-sitter parsers count
    only newlines. Using the parser's own rule keeps every reported line number correct."""
    if python:
        parts = _PY_NEWLINE.split(text)
        if parts and parts[-1] == "":
            parts.pop()
        return parts
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return [line[:-1] if line.endswith("\r") else line for line in lines]


class SourceReader:
    """Verified source lines for one request, read at most once per file."""

    def __init__(self, store: IndexStore) -> None:
        self._store = store
        self._lines: dict[str, list[str] | None] = {}
        self.stale: set[str] = set()
        self.corpus: Any = None  # text/data files, set by the literal search

    def lines(self, path: str) -> list[str] | None:
        if path not in self._lines and self.corpus is not None and path in self.corpus.paths_set:
            self._lines[path] = self.corpus.lines(path)
            if self._lines[path] is None:
                self.stale.add(path)
        if path not in self._lines:
            text = read_indexed_source(self._store, path)
            self._lines[path] = (
                split_lines(text, path.endswith(".py")) if text is not None else None
            )
            if text is None:
                self.stale.add(path)
        return self._lines[path]


class SourceIndex:
    """A synchronized read view of the persistent source postings (use as a context manager)."""

    def __init__(self, store: IndexStore) -> None:
        directory = cache_dir(store.root)
        directory.mkdir(parents=True, exist_ok=True)
        self.store = store
        self._conn = sqlite3.connect(directory / SOURCE_DB, timeout=30)
        self._paths: dict[str, set[str]] = {}
        self._df: dict[str, int] = {}
        self._text: Any = None
        try:
            self._sync()
        except BaseException:
            self._conn.close()
            raise
        n_docs, avg_len = self._conn.execute(
            "SELECT COUNT(*), COALESCE(AVG(length),0) FROM files WHERE length > 0"
        ).fetchone()
        self.n_docs: int = n_docs
        self.avg_len: float = avg_len

    def __enter__(self) -> SourceIndex:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()
        if self._text is not None:
            self._text.close()

    @property
    def text(self) -> Any:
        """Text and data files (locales, config, docs, unparsed languages), for literal search."""
        if self._text is None:
            from prism.navigator.textcorpus import TextCorpus

            self._text = TextCorpus(self.store.root, self.store.manifest)
        return self._text

    def files_with_all_text(self, terms: list[str]) -> set[str]:
        """Code files and text/data files that contain every term."""
        return set(self.files_with_all(terms) | self.text.files_with_all(terms))

    def df_text(self, term: str) -> int:
        return int(self.df(term) + self.text.df(term))

    def _sync(self) -> None:
        conn = self._conn
        conn.executescript(
            "CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, sha TEXT, length INTEGER);"
            "CREATE TABLE IF NOT EXISTS postings (term TEXT, path TEXT, tf REAL);"
            "CREATE INDEX IF NOT EXISTS source_term ON postings(term);"
            "CREATE INDEX IF NOT EXISTS source_path ON postings(path);"
        )
        # Serialize synchronization across MCP/CLI processes; readers see complete revisions.
        conn.execute("BEGIN IMMEDIATE")
        cached = dict(conn.execute("SELECT path, sha FROM files"))
        files = self.store.manifest.get("files", {})
        for file in sorted(set(cached) - set(files)):
            conn.execute("DELETE FROM postings WHERE path = ?", (file,))
            conn.execute("DELETE FROM files WHERE path = ?", (file,))
        for file, facts in sorted(files.items()):
            sha = facts.get("sha256")
            if sha and cached.get(file) == sha:
                continue
            conn.execute("DELETE FROM postings WHERE path = ?", (file,))
            text = read_indexed_source(self.store, file)
            counts: dict[str, int] = {}
            if text is not None:
                counts = dict(term_counts([(file, 3), (text, 1)]))
            conn.execute(
                "INSERT OR REPLACE INTO files VALUES (?,?,?)", (file, sha, sum(counts.values()))
            )
            conn.executemany(
                "INSERT INTO postings VALUES (?,?,?)",
                [(term, file, float(tf)) for term, tf in sorted(counts.items())],
            )
        conn.commit()

    # --- postings ------------------------------------------------------------

    def paths_with(self, term: str) -> set[str]:
        """Every indexed file containing `term` (cached for the life of this object)."""
        found = self._paths.get(term)
        if found is None:
            rows = self._conn.execute("SELECT path FROM postings WHERE term = ?", (term,))
            found = {r[0] for r in rows}
            self._paths[term] = found
            self._df[term] = len(found)
        return found

    def df(self, term: str) -> int:
        known = self._df.get(term)
        if known is None:
            known = self._conn.execute(
                "SELECT COUNT(*) FROM postings WHERE term = ?", (term,)
            ).fetchone()[0]
            self._df[term] = known
        return known

    def idf(self, term: str) -> float:
        """BM25 inverse document frequency; 0 for terms absent from the index."""
        df = self.df(term)
        if df == 0:
            return 0.0
        return math.log(1 + (self.n_docs - df + 0.5) / (df + 0.5))

    def files_with_all(self, terms: list[str]) -> set[str]:
        """Files containing every term (rarest term first, so the intersection stays small)."""
        if not terms:
            return set()
        ordered = sorted(set(terms), key=self.df)
        found = set(self.paths_with(ordered[0]))
        for term in ordered[1:]:
            if not found:
                break
            found &= self.paths_with(term)
        return found

    def scores(self, terms: list[str]) -> dict[str, float]:
        """BM25 score per file, summed over `terms`."""
        scores: dict[str, float] = {}
        for term in sorted(set(terms)):
            rows = self._conn.execute(
                "SELECT p.path, p.tf, f.length FROM postings p JOIN files f ON f.path=p.path "
                "WHERE p.term=?",
                (term,),
            ).fetchall()
            for file, tf, length in rows:
                scores[file] = scores.get(file, 0.0) + bm25(
                    tf, len(rows), self.n_docs, length, self.avg_len
                )
        return scores

    def search(self, query: str, limit: int = 10) -> list[tuple[str, float]]:
        """BM25 over source bodies and paths; tests and migrations rank below application code
        unless the query asks for them."""
        return self.ranked(sorted(set(tokenize(query))), limit)

    def ranked(self, terms: list[str], limit: int = 10) -> list[tuple[str, float]]:
        """`search` for terms that are already tokenized (stemmed) index terms."""
        if not terms:
            return []
        scores = self.scores(terms)
        wants_tests = any(t.startswith("test") or t == "spec" for t in terms)
        wants_migrations = any(t.startswith("migrat") for t in terms)
        for file in scores:
            if not wants_tests and self.store._is_test(file):
                scores[file] *= 0.5
            elif not wants_migrations and "/migrations/" in f"/{file}":
                scores[file] *= 0.35
        return sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:limit]


def pending_files(root: Path, manifest: dict[str, Any]) -> int:
    """How many indexed files the persistent source postings do not yet reflect. Read-only: it
    never builds anything, so it is safe to ask from a hook with a tight time budget."""
    manifest_files = manifest.get("files", {})
    path = cache_dir(root) / SOURCE_DB
    if not path.is_file():
        return len(manifest_files)
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=1)
        try:
            cached = dict(conn.execute("SELECT path, sha FROM files"))
        finally:
            conn.close()
    except sqlite3.Error:
        return len(manifest_files)
    stale = sum(1 for f, e in manifest_files.items() if cached.get(f) != e.get("sha256"))
    return stale + len(set(cached) - set(manifest_files))


def search_sources(store: IndexStore, query: str, limit: int = 10) -> list[tuple[str, float]]:
    """BM25 over source bodies and paths, with changed-file-only cache maintenance.

    Each new session reuses source-v2.sqlite. The manifest is the synchronization
    boundary: external edits must go through update (or a hook) before indexing.
    """
    with SourceIndex(store) as index:
        return index.search(query, limit)
