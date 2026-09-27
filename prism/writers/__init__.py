"""The only package that writes into `.aicontext/`."""

from __future__ import annotations

import contextlib
import time
from pathlib import Path
from typing import Any

from prism import SCHEMA_VERSION, __version__
from prism.core.models import Index
from prism.core.paths import AICONTEXT
from prism.drift import Change, apply_drift
from prism.writers.agents_md import NARRATIVE_SECTIONS, render_agents_md
from prism.writers.artifacts import build_docs
from prism.writers.json_writer import dumps, write_text
from prism.writers.manifest import (
    file_entries,
    load_manifest,
    new_manifest,
    now_iso,
    text_hash,
    write_manifest,
)
from prism.writers.modules_md import module_filename, module_groups, render_module_md

STALE_TEMP_SECONDS = 120


def _remove_stale_temp_files(out_dir: Path) -> None:
    """Remove temp files left by an interrupted, time-boxed hook.

    Only artifact temp files (never the cache, where other processes may be building)
    and only old ones, so a concurrent writer's in-flight file is never touched.
    """
    cutoff = time.time() - STALE_TEMP_SECONDS
    for stray in out_dir.rglob(".*.tmp"):
        if "cache" in stray.relative_to(out_dir).parts:
            continue
        with contextlib.suppress(OSError):
            if stray.stat().st_mtime < cutoff:
                stray.unlink()


def write_index(
    root: Path,
    index: Index,
    manifest: dict[str, Any],
    docs: dict[str, dict[str, Any]] | None = None,
    changes: list[Change] | None = None,
    drift_threshold: int = 8,
    known_hashes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Write every artifact, AGENTS.md, module summaries, and the manifest.

    Returns the updated manifest. Files whose content is unchanged are not
    rewritten, so mtimes stay stable for unchanged artifacts.
    """
    out_dir = root / AICONTEXT
    _remove_stale_temp_files(out_dir)
    docs = docs if docs is not None else build_docs(index)
    known = known_hashes or {}
    artifacts: dict[str, str] = {}

    def put(rel: str, text: str) -> None:
        digest = text_hash(text)
        target = out_dir / rel
        # Skip the read-compare-write when the manifest says the file already has this content.
        try:
            same = known.get(rel) == digest and target.stat().st_size == len(text.encode("utf-8"))
        except OSError:
            same = False
        if not same:
            write_text(target, text)
        artifacts[rel] = digest

    for name, doc in docs.items():
        put(name, dumps(doc))

    agents_path = out_dir / "AGENTS.md"
    existing = agents_path.read_text(encoding="utf-8") if agents_path.is_file() else None
    put("AGENTS.md", render_agents_md(index, existing))

    modules_dir = out_dir / "modules"
    groups = module_groups(index)
    groups_of = {m: g.id for g in groups.values() for m in g.modules}
    wanted = set()
    for group in groups.values():
        path = modules_dir / module_filename(group.id)
        wanted.add(path.name)
        existing_md = path.read_text(encoding="utf-8") if path.is_file() else None
        put(f"modules/{path.name}", render_module_md(index, group, groups_of, existing_md))
    if modules_dir.is_dir():
        for stale in modules_dir.glob("*.md"):
            if stale.name not in wanted:
                stale.unlink()

    sections = {*NARRATIVE_SECTIONS, *(f"modules/{g}" for g in groups)}
    parse_errors = {pf.path: pf.parse_error for pf in index.parsed if pf.parse_error}
    health = docs.get("health.json", {})
    manifest = dict(manifest)
    manifest.update(
        {
            "last_scan": now_iso(),
            "prism_version": __version__,
            "schema_version": SCHEMA_VERSION,
            "files": file_entries(index.files, parse_errors),
            "artifacts": dict(sorted(artifacts.items())),
            "rank_approx": index.rank_approx,
            "drift": apply_drift(
                manifest.get("drift", {}), changes or [], drift_threshold, sections
            ),
            "stats": {
                "files": len(index.files),
                "symbols": len(index.symbols),
                "modules": len(index.import_graph.modules),
                "import_edges": len(index.import_graph.edges),
                "call_edges": len(index.call_graph.edges),
                "test_files": len(index.tests_map.test_files),
                "parse_errors": len(parse_errors),
                "languages": dict(sorted(index.languages.items())),
                "routes": len(index.routes),
                "models": len(index.models),
                "config_keys": len(index.config),
                "dead_code_candidates": len(index.dead_code),
                "smells": sum(health.get("smell_counts", {}).values()),
                "git": bool(index.git and index.git.available),
            },
        }
    )
    write_manifest(root, manifest)
    return manifest


__all__ = ["load_manifest", "new_manifest", "write_index", "write_manifest"]
