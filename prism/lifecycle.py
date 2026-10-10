"""Enable PRISM in a repo (`init`), per-user consent, pause/resume, and scanning.

Every change `init` makes is planned first so the CLI can show it and ask.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from prism.config import load_config
from prism.consent import RepoEntry, get_entry, registry_path, set_entry
from prism.core.errors import UserError
from prism.core.models import GitIntel
from prism.core.paths import AICONTEXT, GITIGNORE_LINES, manifest_path
from prism.discovery import discover
from prism.drift import diff, snapshot
from prism.graph.ranking import LazyRanker, Ranker, pagerank
from prism.health import git_head
from prism.incremental.hash_cache import StateCache
from prism.incremental.lock import UpdateLock
from prism.integrations import (
    FileChange,
    GitHooksIntegration,
    IntegrationOptions,
    all_removals,
    get_integration,
)
from prism.integrations.base import apply_changes, remove_changes
from prism.integrations.git_hooks import make_executable
from prism.parsing import get_parser
from prism.pipeline import build_index
from prism.writers.artifacts import ARTIFACTS, build_docs
from prism.writers.index_writer import write_index
from prism.writers.json_writer import write_text
from prism.writers.manifest import load_manifest, new_manifest, write_manifest

LAZY_RANK_MIN_SYMBOLS = 5000  # below this, every update recomputes PageRank exactly


@dataclass(frozen=True)
class PlannedChange:
    kind: str  # "create" | "modify" | "register"
    target: str
    detail: str


@dataclass(frozen=True)
class InitPlan:
    root: Path
    changes: tuple[PlannedChange, ...]
    missing_gitignore_lines: tuple[str, ...]
    needs_manifest: bool
    needs_registration: bool
    file_changes: tuple[FileChange, ...] = field(default=())

    @property
    def is_noop(self) -> bool:
        return not self.changes


def _gitignore_missing(root: Path) -> tuple[str, ...]:
    path = root / ".gitignore"
    existing: set[str] = set()
    if path.is_file():
        existing = {line.strip() for line in path.read_text(encoding="utf-8").splitlines()}
    return tuple(line for line in GITIGNORE_LINES if line not in existing)


def plan_init(
    root: Path,
    agents: list[str] | tuple[str, ...] = (),
    options: IntegrationOptions | None = None,
    git_hooks: bool = False,
) -> InitPlan:
    """Plan every change `init` would make. Nothing is written."""
    options = options or IntegrationOptions()
    manifest = load_manifest(root)
    changes: list[PlannedChange] = []
    if manifest is None:
        changes.append(
            PlannedChange("create", f"{AICONTEXT}/manifest.json", "new PRISM index directory")
        )
    missing = _gitignore_missing(root)
    if missing:
        verb = "modify" if (root / ".gitignore").is_file() else "create"
        changes.append(PlannedChange(verb, ".gitignore", "add " + ", ".join(missing)))
    entry = get_entry(root)
    repo_id = manifest.get("repo_id") if manifest else None
    needs_registration = entry is None or not entry.enabled or entry.repo_id != repo_id
    if needs_registration:
        changes.append(
            PlannedChange(
                "register", str(registry_path()), "enable PRISM for you in this repo (local only)"
            )
        )
    file_changes: list[FileChange] = []
    for name in agents:
        file_changes.extend(get_integration(name).plan(root, options))
    if git_hooks:
        file_changes.extend(GitHooksIntegration().plan(root, options))
    for fc in file_changes:
        changes.append(PlannedChange(fc.kind(root), fc.path, fc.detail))
    return InitPlan(
        root, tuple(changes), missing, manifest is None, needs_registration, tuple(file_changes)
    )


def apply_init(plan: InitPlan) -> dict[str, Any]:
    root = plan.root
    manifest = load_manifest(root)
    if manifest is None:
        manifest = new_manifest()
        write_manifest(root, manifest)
    if plan.missing_gitignore_lines:
        path = root / ".gitignore"
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        if text and not text.endswith("\n"):
            text += "\n"
        block = "# PRISM (local caches and audit scratch files)\n" + "\n".join(
            plan.missing_gitignore_lines
        )
        write_text(path, text + ("\n" if text else "") + block + "\n")
    if plan.needs_registration:
        set_entry(root, RepoEntry(repo_id=str(manifest["repo_id"]), enabled=True, paused=False))
    if plan.file_changes:
        applied = apply_changes(root, list(plan.file_changes))
        make_executable(root, applied)
    return manifest


GITIGNORE_HEADER = "# PRISM (local caches and audit scratch files)"


def plan_uninstall(root: Path) -> list[FileChange]:
    return all_removals(root)


def apply_uninstall(root: Path, removals: list[FileChange], purge: bool = False) -> None:
    """Remove PRISM-managed integration files. With `purge`, also `.aicontext/` and consent."""
    remove_changes(root, removals)
    if purge:
        shutil.rmtree(root / AICONTEXT, ignore_errors=True)
        set_entry(root, None)
        path = root / ".gitignore"
        if path.is_file():
            lines = path.read_text(encoding="utf-8").splitlines()
            kept = [ln for ln in lines if ln.strip() not in (*GITIGNORE_LINES, GITIGNORE_HEADER)]
            text = "\n".join(kept).strip("\n")
            if text:
                write_text(path, text + "\n")
            else:
                path.unlink()


def require_manifest(root: Path) -> dict[str, Any]:
    manifest = load_manifest(root)
    if manifest is None:
        raise UserError("PRISM is not initialized in this repo. Run `prism init` first.")
    return manifest


@dataclass(frozen=True)
class IndexRun:
    manifest: dict[str, Any]
    changed: tuple[str, ...]
    added: tuple[str, ...]
    deleted: tuple[str, ...]
    reparsed: int
    skipped: bool  # nothing changed, nothing written


def _git_from_state(data: Any) -> GitIntel | None:
    if not isinstance(data, dict) or not data.get("available"):
        return None
    return GitIntel(
        available=True,
        head=data.get("head"),
        commits_analyzed=int(data.get("commits_analyzed", 0)),
        churn=dict(data.get("churn", {})),
        owners={k: [(a, n) for a, n in v] for k, v in data.get("owners", {}).items()},
        last_changed=dict(data.get("last_changed", {})),
        co_change=[(a, b, n, s) for a, b, n, s in data.get("co_change", [])],
    )


def _git_to_state(git: GitIntel | None) -> Any:
    if git is None or not git.available:
        return None
    return {
        "available": True,
        "head": git.head,
        "commits_analyzed": git.commits_analyzed,
        "churn": git.churn,
        "owners": {k: [list(o) for o in v] for k, v in git.owners.items()},
        "last_changed": git.last_changed,
        "co_change": [list(p) for p in git.co_change],
    }


def _snapshot_from_disk(root: Path) -> dict[str, Any] | None:
    """Rebuild the previous structural snapshot from committed artifacts (fresh clone)."""
    out = root / AICONTEXT
    docs: dict[str, dict[str, Any]] = {}
    for name in ARTIFACTS:
        path = out / name
        if path.is_file():
            try:
                docs[name] = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                return None
    return snapshot(docs) if "symbols.json" in docs else None


def run_index(
    root: Path,
    *,
    incremental: bool,
    files: list[str] | None = None,
    full: bool = False,
    lazy_rank: bool = True,
    lock_wait: float = 10.0,
) -> IndexRun:
    """Build (or incrementally update) the index and write `.aicontext/`.

    `scan` = full ranking, parse cache reused unless `full`.
    `update` = only changed files are re-parsed; ranking is lazy; returns
    early without writing anything if no file and no git history changed.
    """
    root = root.resolve()
    require_manifest(root)
    with UpdateLock(root, wait=lock_wait):
        return _run_index_locked(root, incremental, files, full, lazy_rank)


def _run_index_locked(
    root: Path,
    incremental: bool,
    files: list[str] | None,
    full: bool,
    lazy_rank: bool,
) -> IndexRun:
    # Read the manifest only once the lock is held: a writer we waited for has just changed it.
    manifest = require_manifest(root)
    config = load_config(root)
    known: dict[str, Any] = {} if full else dict(manifest.get("files", {}))
    for f in files or []:
        known.pop(f.replace("\\", "/"), None)  # force a re-hash of files named explicitly
    discovered = discover(root, config, known, resniff=not incremental)
    shas = {f.path: f.sha256 for f in discovered}
    previous = {p: e.get("sha256") for p, e in manifest.get("files", {}).items()}
    added = tuple(sorted(set(shas) - set(previous)))
    deleted = tuple(sorted(set(previous) - set(shas)))
    changed = tuple(sorted(p for p in set(shas) & set(previous) if shas[p] != previous[p]))

    with StateCache(root) as state:
        prev_git = _git_from_state(state.get("git"))
        if (
            incremental
            and manifest.get("last_scan")
            and not (added or deleted or changed)
            and (prev_git is None or prev_git.head == git_head(root))
        ):
            return IndexRun(manifest, changed, added, deleted, 0, skipped=True)

        cached = {} if full else state.cached_parses(shas)
        call_ranker: Ranker = pagerank
        import_ranker: Ranker = pagerank
        lazy: list[LazyRanker] = []
        if incremental and lazy_rank and manifest.get("last_scan"):
            prev = state.get("ranks") or {}
            # Exact PageRank costs milliseconds on a small graph, so approximate (kept) scores are
            # only worth their drift on large ones; below the threshold an update equals a scan.
            if prev and len(prev.get("call", {})) >= LAZY_RANK_MIN_SYMBOLS:
                lazy = [
                    LazyRanker(
                        prev.get("call", {}), {(a, b) for a, b in prev.get("call_edges", [])}
                    ),
                    LazyRanker(
                        prev.get("import", {}), {(a, b) for a, b in prev.get("import_edges", [])}
                    ),
                ]
                call_ranker, import_ranker = lazy
        index = build_index(
            root,
            config,
            files=discovered,
            cached=cached,
            call_ranker=call_ranker,
            import_ranker=import_ranker,
            previous_git=prev_git,
        )
        index.rank_approx = any(r.approx for r in lazy) or (
            bool(manifest.get("rank_approx")) and bool(lazy) and not any(r.ran_full for r in lazy)
        )
        docs = build_docs(index)
        new_snap = snapshot(docs)
        old_snap = state.get("snapshot") or _snapshot_from_disk(root)
        changes = diff(old_snap, new_snap) if old_snap and manifest.get("last_scan") else []
        manifest = write_index(
            root,
            index,
            manifest,
            docs,
            changes,
            config.drift_threshold,
            # Full scans rewrite everything (repairing hand edits); updates trust the manifest.
            known_hashes=manifest.get("artifacts", {}) if incremental else None,
        )

        state.store_parses(index.parsed, shas, only={p for p in shas if p not in cached})
        state.put("snapshot", new_snap)
        state.put(
            "ranks",
            {
                "call": index.call_graph.rank,
                "call_edges": sorted([e.source, e.target] for e in index.call_graph.edges),
                "import": {m.id: m.rank for m in index.import_graph.modules.values()},
                "import_edges": sorted([e.source, e.target] for e in index.import_graph.edges),
            },
        )
        state.put("git", _git_to_state(index.git))
    parseable = {f.path for f in discovered if get_parser(f.language) is not None}
    reparsed = sum(1 for p in parseable if p not in cached)
    return IndexRun(manifest, changed, added, deleted, reparsed, skipped=False)


def scan(root: Path, full: bool = False, warm: bool = True) -> dict[str, Any]:
    """Build the whole index. By default the query caches are built too, so the first question
    after a scan (or the first prompt a hook sees) is as fast as every later one."""
    manifest = run_index(root, incremental=False, full=full).manifest
    if warm:
        from prism.navigator.freshness import warm_caches

        warm_caches(root.resolve())
    return manifest


def update(
    root: Path,
    files: list[str] | None = None,
    lazy_rank: bool = True,
    lock_wait: float = 10.0,
) -> IndexRun:
    return run_index(root, incremental=True, files=files, lazy_rank=lazy_rank, lock_wait=lock_wait)


def set_enabled(root: Path, enabled: bool) -> None:
    manifest = require_manifest(root)
    if enabled:
        entry = get_entry(root)
        paused = entry.paused if entry and entry.repo_id == manifest["repo_id"] else False
        set_entry(root, RepoEntry(str(manifest["repo_id"]), True, paused))
    else:
        set_entry(root, None)


def set_paused(root: Path, paused: bool) -> None:
    manifest = require_manifest(root)
    entry = get_entry(root)
    if entry is None or not entry.enabled or entry.repo_id != manifest["repo_id"]:
        raise UserError("PRISM is not enabled for you in this repo. Run `prism enable` first.")
    set_entry(root, RepoEntry(entry.repo_id, True, paused))


def is_initialized(root: Path) -> bool:
    return manifest_path(root).is_file()
