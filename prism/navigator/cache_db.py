"""SQLite query cache in `.aicontext/cache/`, rebuilt from the JSON artifacts.

The JSON files are the source of truth. The cache is disposable: it is
keyed by the artifact hashes in `manifest.json` and rebuilt whenever they
change. Each build gets its own file name so a reader holding an old
connection (e.g. the MCP server) never blocks a rebuild.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sqlite3
import threading
import uuid
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from prism.core.paths import AICONTEXT
from prism.navigator.text import term_counts

CACHE_FORMAT = "9"  # route documents aggregate distinct handlers sharing a method/path

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE symbols (
    id TEXT PRIMARY KEY, name TEXT, kind TEXT, module TEXT, file TEXT,
    start INTEGER, "end" INTEGER, signature TEXT, doc TEXT, visibility TEXT,
    parent TEXT, rank REAL, tokens_est INTEGER
);
CREATE INDEX symbols_name ON symbols(name);
CREATE INDEX symbols_file ON symbols(file);
CREATE TABLE calls (src TEXT, dst TEXT, confidence TEXT, line INTEGER, resolution TEXT);
CREATE INDEX calls_src ON calls(src);
CREATE INDEX calls_dst ON calls(dst);
CREATE TABLE modules (
    id TEXT PRIMARY KEY, file TEXT, is_package INTEGER, doc TEXT, rank REAL, entry_point TEXT
);
CREATE INDEX modules_file ON modules(file);
CREATE TABLE imports (src TEXT, dst TEXT);
CREATE INDEX imports_src ON imports(src);
CREATE INDEX imports_dst ON imports(dst);
CREATE TABLE externals (module TEXT, name TEXT);
CREATE TABLE files (path TEXT PRIMARY KEY, language TEXT, size INTEGER, parse_error TEXT);
CREATE TABLE tests_sym (symbol TEXT, test TEXT);
CREATE INDEX tests_sym_symbol ON tests_sym(symbol);
CREATE TABLE tests_file (file TEXT, test TEXT);
CREATE INDEX tests_file_file ON tests_file(file);
CREATE TABLE routes (method TEXT, path TEXT, handler TEXT, file TEXT, line INTEGER, framework TEXT);
CREATE TABLE cochange (a TEXT, b TEXT, count INTEGER, strength REAL);
CREATE INDEX cochange_a ON cochange(a);
CREATE TABLE health_file (path TEXT PRIMARY KEY, risk REAL, data TEXT);
CREATE TABLE health_sym (id TEXT PRIMARY KEY, risk REAL, data TEXT);
CREATE TABLE blast (kind TEXT, id TEXT, count INTEGER, top TEXT, PRIMARY KEY (kind, id));
CREATE TABLE config_reads (key TEXT, kind TEXT, symbol TEXT, file TEXT, line INTEGER);
CREATE INDEX config_reads_symbol ON config_reads(symbol);
CREATE TABLE models (id TEXT PRIMARY KEY, data TEXT);
CREATE TABLE docs (doc_id INTEGER PRIMARY KEY, kind TEXT, ref TEXT, length INTEGER);
CREATE UNIQUE INDEX docs_identity ON docs(kind, ref);
CREATE TABLE search_facts (doc_id INTEGER PRIMARY KEY, digest TEXT);
CREATE TABLE postings (term TEXT, doc_id INTEGER, tf REAL);
CREATE INDEX postings_term ON postings(term);
CREATE INDEX postings_doc ON postings(doc_id);
"""

OPTIONAL_ARTIFACTS = (
    "routes.json",
    "models.json",
    "config.json",
    "health.json",
    "git_intelligence.json",
    "blast_radius.json",
)

_SNAPSHOT: ContextVar[dict[Path, Any] | None] = ContextVar("prism_artifact_snapshot", default=None)


def _artifact_snapshot(root: Path, manifest: dict[str, Any]) -> dict[Path, Any]:
    from prism.core.errors import IndexStaleError

    out = root / AICONTEXT
    snapshot: dict[Path, Any] = {}
    names = (
        "symbols.json",
        "call_graph.json",
        "dependency_graph.json",
        "tests_map.json",
        *OPTIONAL_ARTIFACTS,
    )
    for name in names:
        path = out / name
        expected = manifest.get("artifacts", {}).get(name)
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            if expected:
                raise IndexStaleError(
                    f"Index artifact unavailable: {name}; retry after prism update.", retryable=True
                ) from None
            snapshot[path] = None
            continue
        if expected and hashlib.sha256(raw).hexdigest() != expected:
            raise IndexStaleError(
                f"Index generation changed: {name}; retry after prism update.", retryable=True
            )
        snapshot[path] = json.loads(raw)
    return snapshot


def _read(path: Path) -> Any:
    snapshot = _SNAPSHOT.get()
    if snapshot is not None and path in snapshot:
        return snapshot[path]
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def fingerprint(manifest: dict[str, Any]) -> str:
    artifacts = manifest.get("artifacts", {})
    sources = {p: f.get("sha256") for p, f in manifest.get("files", {}).items()}
    blob = json.dumps(
        {"format": CACHE_FORMAT, "artifacts": artifacts, "sources": sources}, sort_keys=True
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def cache_dir(root: Path) -> Path:
    from prism.consent import cache_root

    return cache_root(root)


_BUILD_LOCK = threading.Lock()


def purge_disposable_caches(root: Path) -> int:
    """Delete every SQLite cache of this repo. They are all rebuilt from the JSON artifacts or the
    source, so a damaged one (killed process, full disk, antivirus) is cheaper to drop than to
    repair. Sessions, the work log and the activity trail are not databases and are kept."""
    removed = 0
    directory = cache_dir(root)
    for pattern in ("*.sqlite", "*.sqlite-wal", "*.sqlite-shm", "*.sqlite-journal", ".index-*.tmp"):
        for path in directory.glob(pattern):
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def open_cache(root: Path, manifest: dict[str, Any]) -> sqlite3.Connection:
    """Open (building if needed) the cache for the current artifacts.

    Safe under concurrency: builds are serialised within a process, every builder writes
    its own uniquely named temp file, and a builder that loses the race to another
    process simply uses the winner's file.
    """
    fp = fingerprint(manifest)
    directory = cache_dir(root)
    path = directory / f"index-{fp}.sqlite"
    for attempt in range(3):
        if not path.is_file():
            with _BUILD_LOCK:
                if not path.is_file():  # another thread may have built it while we waited
                    _build_file(root, manifest, fp, directory, path)
        try:
            conn = sqlite3.connect(
                f"file:{path.as_posix()}?mode=ro", uri=True, check_same_thread=False
            )
            break
        except sqlite3.OperationalError:
            # Another process can retire this generation between the existence
            # check and opening it. Retry only a disappeared path, not SQL/lock errors.
            if path.is_file() or attempt == 2:
                raise
    conn.row_factory = sqlite3.Row
    return conn


def _build_file(root: Path, manifest: dict[str, Any], fp: str, directory: Path, path: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    tmp = (
        directory / f".index-{fp}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex[:8]}.tmp"
    )
    from prism.navigator.delta_cache import DeltaConnection

    conn: sqlite3.Connection = sqlite3.connect(tmp, factory=DeltaConnection)
    reused = False
    try:
        snapshot = _artifact_snapshot(root, manifest)
        candidates = []
        for previous in directory.glob("index-*.sqlite"):
            try:
                candidates.append((previous.stat().st_mtime_ns, previous))
            except FileNotFoundError:
                continue  # another process retired this generation
        for _, previous in sorted(candidates, reverse=True):
            old = None
            try:
                old = sqlite3.connect(f"file:{previous.as_posix()}?mode=ro", uri=True)
                row = old.execute("SELECT value FROM meta WHERE key='format'").fetchone()
                if row is not None and row[0] == CACHE_FORMAT:
                    old.backup(conn)
                    reused = True
                    break
            except sqlite3.DatabaseError:
                continue
            finally:
                if old is not None:
                    old.close()
        if not reused:
            conn.close()
            conn = sqlite3.connect(tmp)
        token = _SNAPSHOT.set(snapshot)
        try:
            _build(conn, root / AICONTEXT, manifest)
        finally:
            _SNAPSHOT.reset(token)
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('fingerprint', ?)", (fp,))
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('format', ?)", (CACHE_FORMAT,))
        conn.execute(
            "INSERT OR REPLACE INTO meta VALUES ('build_mode', ?)", ("delta" if reused else "full",)
        )
        if reused:
            assert isinstance(conn, DeltaConnection)
            conn.execute(
                "INSERT OR REPLACE INTO meta VALUES ('rows_changed', ?)",
                (str(conn.rows_inserted + conn.rows_deleted),),
            )
        conn.commit()
    except BaseException:
        conn.close()
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise
    conn.close()
    try:
        os.replace(tmp, path)
    except OSError:  # another process won the race (or the target is open on Windows)
        with contextlib.suppress(OSError):
            tmp.unlink()
    for obsolete in directory.glob("index-*.sqlite"):
        if obsolete != path:
            with contextlib.suppress(OSError):  # still open elsewhere (Windows)
                obsolete.unlink()


def _build(conn: sqlite3.Connection, out: Path, manifest: dict[str, Any]) -> None:
    conn.executescript(SCHEMA)
    symbols = (_read(out / "symbols.json") or {}).get("symbols", [])
    conn.executemany(
        "INSERT INTO symbols VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                s["id"],
                s["id"].rsplit(".", 1)[-1],
                s["kind"],
                s["module"],
                s["file"],
                s["lines"][0],
                s["lines"][1],
                s["signature"],
                s["doc"],
                s["visibility"],
                s["parent"],
                s["rank"],
                s["tokens_est"],
            )
            for s in symbols
        ],
    )
    calls = (_read(out / "call_graph.json") or {}).get("edges", [])
    conn.executemany(
        "INSERT INTO calls VALUES (?,?,?,?,?)",
        [
            (
                e["from"],
                e["to"],
                e["confidence"],
                e["line"],
                e.get("resolution", "name" if e["confidence"] == "low" else "resolved"),
            )
            for e in calls
        ],
    )
    dep = _read(out / "dependency_graph.json") or {}
    modules = dep.get("modules", [])
    conn.executemany(
        "INSERT INTO modules VALUES (?,?,?,?,?,?)",
        [
            (
                m["id"],
                m["file"],
                int(m["is_package"]),
                m.get("doc", ""),
                m["rank"],
                m["entry_point"],
            )
            for m in modules
        ],
    )
    conn.executemany(
        "INSERT INTO imports VALUES (?,?)", [(e["from"], e["to"]) for e in dep.get("edges", [])]
    )
    conn.executemany(
        "INSERT INTO externals VALUES (?,?)",
        [(m["id"], name) for m in modules for name in m["external"]],
    )
    conn.executemany(
        "INSERT INTO files VALUES (?,?,?,?)",
        [
            (path, f.get("language"), f.get("size"), f.get("parse_error"))
            for path, f in sorted(manifest.get("files", {}).items())
        ],
    )
    tm = _read(out / "tests_map.json") or {}
    conn.executemany(
        "INSERT INTO tests_sym VALUES (?,?)",
        [(k, t) for k, tests in tm.get("by_symbol", {}).items() for t in tests],
    )
    conn.executemany(
        "INSERT INTO tests_file VALUES (?,?)",
        [(k, t) for k, tests in tm.get("by_file", {}).items() for t in tests],
    )
    _build_optional(conn, out)
    _build_search(conn, symbols, modules, manifest, out / "decisions")


def _build_optional(conn: sqlite3.Connection, out: Path) -> None:
    routes = (_read(out / "routes.json") or {}).get("routes", [])
    conn.executemany(
        "INSERT INTO routes VALUES (?,?,?,?,?,?)",
        [
            (r["method"], r["path"], r["handler"], r["file"], r["line"], r["framework"])
            for r in routes
        ],
    )
    git = _read(out / "git_intelligence.json") or {}
    rows = []
    for pair in git.get("co_change", []):
        rows.append((pair["a"], pair["b"], pair["count"], pair["strength"]))
        rows.append((pair["b"], pair["a"], pair["count"], pair["strength"]))
    conn.executemany("INSERT INTO cochange VALUES (?,?,?,?)", rows)
    health = _read(out / "health.json") or {}
    conn.executemany(
        "INSERT INTO health_file VALUES (?,?,?)",
        [(p, h.get("risk", 0.0), json.dumps(h)) for p, h in health.get("files", {}).items()],
    )
    conn.executemany(
        "INSERT INTO health_sym VALUES (?,?,?)",
        [(i, h.get("risk", 0.0), json.dumps(h)) for i, h in health.get("symbols", {}).items()],
    )
    blast = _read(out / "blast_radius.json") or {}
    conn.executemany(
        "INSERT INTO blast VALUES (?,?,?,?)",
        [
            (kind, k, v["count"], json.dumps(v["top"]))
            for kind in ("files", "symbols")
            for k, v in blast.get(kind, {}).items()
        ],
    )
    config = (_read(out / "config.json") or {}).get("keys", [])
    conn.executemany(
        "INSERT INTO config_reads VALUES (?,?,?,?,?)",
        [
            (k["key"], k["kind"], r["symbol"], r["file"], r["line"])
            for k in config
            for r in k["reads"]
        ],
    )
    models = (_read(out / "models.json") or {}).get("models", [])
    conn.executemany("INSERT INTO models VALUES (?,?)", [(m["id"], json.dumps(m)) for m in models])


def _build_search(
    conn: sqlite3.Connection,
    symbols: list[dict[str, Any]],
    modules: list[dict[str, Any]],
    manifest: dict[str, Any],
    decisions_dir: Path,
) -> None:
    docs: list[tuple[int, str, str, int]] = []
    postings: list[tuple[str, int, float]] = []
    facts: list[tuple[int, str]] = []
    existing = {
        (kind, ref): (ident, length, digest)
        for ident, kind, ref, length, digest in conn.execute(
            "SELECT d.doc_id,d.kind,d.ref,d.length,s.digest FROM docs d JOIN search_facts s USING(doc_id)"
        )
    }
    next_id = max((row[0] for row in existing.values()), default=-1) + 1

    def add(kind: str, ref: str, fields: list[tuple[str, int]]) -> None:
        nonlocal next_id
        digest = hashlib.sha256(json.dumps(fields).encode()).hexdigest()
        old = existing.get((kind, ref))
        doc_id = old[0] if old else next_id
        if old is None:
            next_id += 1
        if old and old[2] == digest:
            docs.append((doc_id, kind, ref, old[1]))
            facts.append((doc_id, digest))
            postings.extend(
                (term, doc_id, tf)
                for term, tf in conn.execute(
                    "SELECT term,tf FROM postings WHERE doc_id=?", (doc_id,)
                )
            )
            return
        counts = term_counts(fields)
        docs.append((doc_id, kind, ref, sum(counts.values())))
        facts.append((doc_id, digest))
        postings.extend((term, doc_id, float(tf)) for term, tf in sorted(counts.items()))

    for s in symbols:
        name = s["id"].rsplit(".", 1)[-1]
        add(
            "symbol",
            s["id"],
            [(name, 3), (s["id"], 1), (s["doc"], 1), (s["signature"], 1), (s["file"], 1)],
        )
    python_files = set()
    for m in modules:
        python_files.add(m["file"])
        add("module", m["id"], [(m["id"], 3), (m.get("doc", ""), 1), (m["file"], 1)])
    for path in sorted(manifest.get("files", {})):
        if path not in python_files:
            add("file", path, [(path, 3)])
    try:
        routes = conn.execute("SELECT method, path, handler FROM routes").fetchall()
    except sqlite3.Error:
        routes = []
    # A path is relative to its router/module: multiple legitimate handlers can
    # share it. Keep one searchable endpoint reference with every handler; the
    # routes table retains their individual source locations and relationships.
    endpoints: dict[tuple[str, str], set[str]] = {}
    for method, path, handler in routes:
        endpoints.setdefault((method, path), set()).add(handler or "")
    for (method, path), handlers in sorted(endpoints.items()):
        add(
            "route",
            f"{method} {path}",
            [(path, 3), (method, 1), *((handler, 1) for handler in sorted(handlers))],
        )
    for decision in (
        sorted(decisions_dir.glob("[0-9][0-9][0-9][0-9]-*.md")) if decisions_dir.is_dir() else []
    ):
        text = decision.read_text(encoding="utf-8")
        title = text.splitlines()[0] if text else decision.stem
        add("decision", decision.stem, [(title, 3), (text, 1)])
    conn.executemany("INSERT INTO docs VALUES (?,?,?,?)", docs)
    conn.executemany("INSERT INTO search_facts VALUES (?,?)", facts)
    conn.executemany("INSERT INTO postings VALUES (?,?,?)", postings)
    avg = sum(d[3] for d in docs) / len(docs) if docs else 0.0
    conn.executemany(
        "INSERT INTO meta VALUES (?,?)", [("n_docs", str(len(docs))), ("avg_len", str(avg))]
    )
