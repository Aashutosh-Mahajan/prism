"""Read access to the index for every navigator query (CLI, MCP, viewer)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from prism.core.errors import IndexMissingError
from prism.core.paths import AICONTEXT
from prism.extractors.tests_map import is_test_file
from prism.navigator.cache_db import fingerprint, open_cache
from prism.navigator.text import bm25, tokenize
from prism.writers.manifest import load_manifest

if TYPE_CHECKING:
    from prism.navigator.graphify import GraphifyGraph

TEST_DEMOTION = 0.5
MIGRATION_DEMOTION = 0.35


@dataclass(frozen=True)
class SymbolRow:
    id: str
    name: str
    kind: str
    module: str
    file: str
    start: int
    end: int
    signature: str
    doc: str
    visibility: str
    parent: str | None
    rank: float
    tokens_est: int

    @property
    def lines(self) -> tuple[int, int]:
        return (self.start, self.end)


@dataclass(frozen=True)
class ModuleRow:
    id: str
    file: str
    is_package: bool
    doc: str
    rank: float
    entry_point: str | None


@dataclass(frozen=True)
class Link:
    """A call-graph neighbour: the symbol and the call-site line in the caller."""

    symbol: SymbolRow
    line: int | None
    confidence: str


@dataclass(frozen=True)
class SearchHit:
    kind: str
    ref: str
    score: float


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class IndexStore:
    def __init__(self, root: Path, manifest: dict[str, Any], conn: sqlite3.Connection) -> None:
        self.root = root
        self._test_dirs: tuple[str, ...] | None = None
        self.manifest = manifest
        self.conn = conn
        self._fingerprint = fingerprint(manifest)
        self._findings: list[dict[str, Any]] | None = None
        self.graphify_graph: GraphifyGraph | None = None
        self.graphify_revision: tuple[str, int, int, int] | None = None

    @classmethod
    def open(cls, root: Path) -> IndexStore:
        root = root.resolve()
        manifest = load_manifest(root)
        if manifest is None:
            raise IndexMissingError(
                "PRISM is not initialized in this repo. If the user wants PRISM here they run "
                "`prism init`; agents must not run it on their own. Otherwise continue without PRISM."
            )
        if not manifest.get("last_scan"):
            raise IndexMissingError("The index has not been built yet. Run `prism scan`.")
        return cls(root, manifest, open_cache(root, manifest))

    def is_current(self) -> bool:
        manifest = load_manifest(self.root)
        return manifest is not None and fingerprint(manifest) == self._fingerprint

    def close(self) -> None:
        self.conn.close()

    # --- symbols -------------------------------------------------------------

    def _sym(self, row: sqlite3.Row | None) -> SymbolRow | None:
        if row is None:
            return None
        return SymbolRow(*tuple(row))

    def _syms(self, sql: str, params: tuple[Any, ...] = ()) -> list[SymbolRow]:
        return [SymbolRow(*tuple(r)) for r in self.conn.execute(sql, params)]

    def symbol(self, sid: str) -> SymbolRow | None:
        return self._sym(self.conn.execute("SELECT * FROM symbols WHERE id = ?", (sid,)).fetchone())

    def symbols_named(self, name: str) -> list[SymbolRow]:
        return self._syms("SELECT * FROM symbols WHERE name = ? ORDER BY rank DESC, id", (name,))

    def symbols_with_suffix(self, suffix: str) -> list[SymbolRow]:
        return self._syms(
            "SELECT * FROM symbols WHERE id = ? OR id LIKE ? ESCAPE '\\' ORDER BY rank DESC, id",
            (suffix, "%." + _escape_like(suffix)),
        )

    def symbols_in_file(self, path: str) -> list[SymbolRow]:
        return self._syms("SELECT * FROM symbols WHERE file = ? ORDER BY start, id", (path,))

    def symbol_at(self, path: str, line: int) -> SymbolRow | None:
        rows = self._syms(
            'SELECT * FROM symbols WHERE file = ? AND start <= ? AND "end" >= ? '
            'ORDER BY ("end" - start), start DESC',
            (path, line, line),
        )
        return rows[0] if rows else None

    def symbol_names(self) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT DISTINCT name FROM symbols ORDER BY name")]

    def top_symbols(self, limit: int, public_only: bool = True) -> list[SymbolRow]:
        where = "WHERE visibility = 'public'" if public_only else ""
        return self._syms(f"SELECT * FROM symbols {where} ORDER BY rank DESC, id LIMIT ?", (limit,))

    def all_symbols(self) -> list[SymbolRow]:
        return self._syms("SELECT * FROM symbols ORDER BY id")

    def children(self, sid: str) -> list[SymbolRow]:
        return self._syms("SELECT * FROM symbols WHERE parent = ? ORDER BY start", (sid,))

    # --- call graph ----------------------------------------------------------

    def callers(self, sid: str) -> list[Link]:
        rows = self.conn.execute(
            "SELECT s.*, c.line, c.confidence FROM calls c JOIN symbols s ON s.id = c.src "
            "WHERE c.dst = ? ORDER BY s.rank DESC, s.id",
            (sid,),
        )
        return [Link(SymbolRow(*tuple(r)[:13]), r["line"], r["confidence"]) for r in rows]

    def callees(self, sid: str) -> list[Link]:
        rows = self.conn.execute(
            "SELECT s.*, c.line, c.confidence FROM calls c JOIN symbols s ON s.id = c.dst "
            "WHERE c.src = ? ORDER BY c.line, s.id",
            (sid,),
        )
        return [Link(SymbolRow(*tuple(r)[:13]), r["line"], r["confidence"]) for r in rows]

    def call_edges(self) -> list[tuple[str, str, str]]:
        rows = self.conn.execute("SELECT src, dst, confidence FROM calls")
        return [(r[0], r[1], r[2]) for r in rows]

    # --- modules and files ---------------------------------------------------

    def _mod(self, row: sqlite3.Row | None) -> ModuleRow | None:
        if row is None:
            return None
        return ModuleRow(
            row["id"],
            row["file"],
            bool(row["is_package"]),
            row["doc"] or "",
            row["rank"],
            row["entry_point"],
        )

    def module(self, mid: str) -> ModuleRow | None:
        return self._mod(self.conn.execute("SELECT * FROM modules WHERE id = ?", (mid,)).fetchone())

    def module_for_file(self, path: str) -> ModuleRow | None:
        return self._mod(
            self.conn.execute("SELECT * FROM modules WHERE file = ?", (path,)).fetchone()
        )

    def modules(self) -> list[ModuleRow]:
        rows = self.conn.execute("SELECT * FROM modules ORDER BY id").fetchall()
        return [m for m in (self._mod(r) for r in rows) if m is not None]

    def modules_with_prefix(self, prefix: str) -> list[ModuleRow]:
        rows = self.conn.execute(
            "SELECT * FROM modules WHERE id = ? OR id LIKE ? ESCAPE '\\' ORDER BY id",
            (prefix, _escape_like(prefix) + ".%"),
        ).fetchall()
        return [m for m in (self._mod(r) for r in rows) if m is not None]

    def imports_of(self, mid: str) -> list[str]:
        return [
            r[0]
            for r in self.conn.execute("SELECT dst FROM imports WHERE src = ? ORDER BY dst", (mid,))
        ]

    def importers_of(self, mid: str) -> list[str]:
        return [
            r[0]
            for r in self.conn.execute("SELECT src FROM imports WHERE dst = ? ORDER BY src", (mid,))
        ]

    def import_edges(self) -> list[tuple[str, str]]:
        return [(r[0], r[1]) for r in self.conn.execute("SELECT src, dst FROM imports")]

    def externals_of(self, mid: str) -> list[str]:
        return [
            r[0]
            for r in self.conn.execute(
                "SELECT name FROM externals WHERE module = ? ORDER BY name", (mid,)
            )
        ]

    def file_exists(self, path: str) -> bool:
        return (
            self.conn.execute("SELECT 1 FROM files WHERE path = ?", (path,)).fetchone() is not None
        )

    def files_with_suffix(self, suffix: str) -> list[str]:
        suffix = suffix.replace("\\", "/").lstrip("./")
        return [
            r[0]
            for r in self.conn.execute(
                "SELECT path FROM files WHERE path = ? OR path LIKE ? ESCAPE '\\' ORDER BY path",
                (suffix, "%/" + _escape_like(suffix)),
            )
        ]

    def file_language(self, path: str) -> str | None:
        row = self.conn.execute("SELECT language FROM files WHERE path = ?", (path,)).fetchone()
        return row[0] if row else None

    def all_files(self) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT path FROM files ORDER BY path")]

    # --- tests, git, health --------------------------------------------------

    def tests_for_symbol(self, sid: str) -> list[str]:
        return [
            r[0]
            for r in self.conn.execute(
                "SELECT test FROM tests_sym WHERE symbol = ? ORDER BY test", (sid,)
            )
        ]

    def tests_for_file(self, path: str) -> list[str]:
        return [
            r[0]
            for r in self.conn.execute(
                "SELECT test FROM tests_file WHERE file = ? ORDER BY test", (path,)
            )
        ]

    def test_files(self) -> set[str]:
        # Unmapped tests still matter: a framework callback or a placeholder test may
        # have neither an import edge nor a resolved call to application code.
        return {path for path in self.all_files() if self._is_test(path)}

    def cochanged(self, path: str, limit: int = 5) -> list[tuple[str, float]]:
        rows = self.conn.execute(
            "SELECT b, strength FROM cochange WHERE a = ? ORDER BY strength DESC, count DESC, b LIMIT ?",
            (path, limit),
        )
        return [(r[0], r[1]) for r in rows]

    def health_symbol(self, sid: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT data FROM health_sym WHERE id = ?", (sid,)).fetchone()
        return json.loads(row[0]) if row else None

    def health_file(self, path: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT data FROM health_file WHERE path = ?", (path,)).fetchone()
        return json.loads(row[0]) if row else None

    def blast(self, kind: str, key: str) -> tuple[int, list[str]] | None:
        row = self.conn.execute(
            "SELECT count, top FROM blast WHERE kind = ? AND id = ?", (kind, key)
        ).fetchone()
        return (row[0], json.loads(row[1])) if row else None

    def routes(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM routes ORDER BY path, method")
        return [dict(r) for r in rows]

    def routes_for_handler(self, sid: str) -> list[dict[str, Any]]:
        return [
            dict(r) for r in self.conn.execute("SELECT * FROM routes WHERE handler = ?", (sid,))
        ]

    def config_reads(self, sid: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT key FROM config_reads WHERE symbol = ? ORDER BY key", (sid,)
        )
        return [r[0] for r in rows]

    def model(self, sid: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT data FROM models WHERE id = ?", (sid,)).fetchone()
        return json.loads(row[0]) if row else None

    # --- audit findings (read live; they change without a rescan) ------------

    def findings(self) -> list[dict[str, Any]]:
        if self._findings is None:
            path = self.root / AICONTEXT / "audit" / "findings.json"
            data: Any = None
            if path.is_file():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    data = None
            self._findings = list((data or {}).get("findings", []))
        return self._findings

    def open_findings(
        self, symbol: str | None = None, file: str | None = None
    ) -> list[dict[str, Any]]:
        out = []
        for f in self.findings():
            if f.get("status") != "open":
                continue
            if (symbol and f.get("symbol") == symbol) or (file and f.get("file") == file):
                out.append(f)
        return out

    # --- search --------------------------------------------------------------

    def _is_test(self, path: str) -> bool:
        if self._test_dirs is None:
            from prism.config import load_config

            self._test_dirs = load_config(self.root).test_dirs
        return is_test_file(path, self._test_dirs)

    def search(self, query: str, limit: int = 10) -> list[SearchHit]:
        terms = sorted(set(tokenize(query)))
        if not terms:
            return []
        meta = dict(self.conn.execute("SELECT key, value FROM meta").fetchall())
        n_docs = int(meta.get("n_docs", "0"))
        avg_len = float(meta.get("avg_len", "0"))
        scores: dict[int, float] = {}
        for term in terms:
            rows = self.conn.execute(
                "SELECT p.doc_id, p.tf, d.length FROM postings p JOIN docs d ON d.doc_id = p.doc_id "
                "WHERE p.term = ?",
                (term,),
            ).fetchall()
            df = len(rows)
            for doc_id, tf, length in rows:
                scores[doc_id] = scores.get(doc_id, 0.0) + bm25(tf, df, n_docs, length, avg_len)
        if not scores:
            return []
        ids = sorted(scores, key=lambda d: (-scores[d], d))[: max(limit * 5, 50)]
        placeholders = ",".join("?" * len(ids))
        docs = {
            r[0]: (r[1], r[2])
            for r in self.conn.execute(
                f"SELECT doc_id, kind, ref FROM docs WHERE doc_id IN ({placeholders})", ids
            )
        }
        hits: list[SearchHit] = []
        max_rank = self.conn.execute("SELECT MAX(rank) FROM symbols").fetchone()[0] or 1.0
        # Most searches look for code to read or change: tests and generated migrations rank
        # below application code unless the query is about them.
        wants_tests = any(t.startswith("test") or t == "spec" for t in terms)
        wants_migrations = any(t.startswith("migrat") for t in terms)
        for doc_id in ids:
            kind, ref = docs[doc_id]
            score = scores[doc_id]
            file: str | None = ref if kind == "file" else None
            if kind == "symbol":
                sym = self.symbol(ref)
                if sym is not None:
                    file = sym.file
                    score *= 1.0 + 0.5 * (sym.rank / max_rank)
                    if sym.name.lower() in terms or sym.name.lower() == query.strip().lower():
                        score *= 1.5
            elif kind == "module":
                mod = self.module(ref)
                file = mod.file if mod else None
            if file:
                if not wants_tests and self._is_test(file):
                    score *= TEST_DEMOTION
                elif not wants_migrations and "/migrations/" in f"/{file}":
                    score *= MIGRATION_DEMOTION
            hits.append(SearchHit(kind, ref, round(score, 4)))
        hits.sort(key=lambda h: (-h.score, h.kind, h.ref))
        return hits[:limit]
