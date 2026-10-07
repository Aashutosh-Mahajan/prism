"""`prism doctor`, `prism migrate`, and `prism watch`."""

from __future__ import annotations

import json
import shutil
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from prism import SCHEMA_VERSION, __version__
from prism.consent import RepoState, repo_state
from prism.core.errors import NotEnabledError, UserError
from prism.core.paths import AICONTEXT
from prism.writers.manifest import load_manifest, text_hash, write_manifest

SCHEMAS = Path(__file__).resolve().parent / "schemas"


@dataclass(frozen=True)
class Check:
    name: str
    status: str  # "ok" | "warn" | "fail"
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


def _version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(p) for p in v.split(".") if p.isdigit())


def doctor(root: Path) -> list[Check]:
    checks: list[Check] = []

    def add(name: str, ok: bool | None, detail: str, warn_only: bool = False) -> None:
        status = "ok" if ok else ("warn" if warn_only or ok is None else "fail")
        checks.append(Check(name, status, detail))

    add("python", sys.version_info >= (3, 10), f"{sys.version.split()[0]} ({sys.platform})")
    add("prism", True, __version__)
    exe = shutil.which("prism")
    add("prism on PATH", exe is not None, exe or "not found: hooks and the MCP server call `prism`")

    manifest = load_manifest(root)
    if manifest is None:
        add(
            "initialized",
            None,
            "not initialized here (run `prism init` if you want PRISM in this repo)",
        )
        return checks
    add("initialized", True, (root / AICONTEXT).as_posix())
    try:
        import jsonschema

        jsonschema.validate(
            manifest, json.loads((SCHEMAS / "manifest.schema.json").read_text(encoding="utf-8"))
        )
        add("manifest schema", True, f"schema {manifest.get('schema_version')}")
    except Exception as exc:  # jsonschema.ValidationError and friends
        add("manifest schema", False, f"invalid manifest: {str(exc).splitlines()[0]}")
    if manifest.get("schema_version") != SCHEMA_VERSION or _version_tuple(
        str(manifest.get("prism_version", "0"))
    ) < _version_tuple(__version__):
        add(
            "index version",
            None,
            f"built by prism {manifest.get('prism_version')}; run `prism migrate`",
            warn_only=True,
        )
    else:
        add("index version", True, f"prism {manifest.get('prism_version')}")

    state = repo_state(root, manifest.get("repo_id"))
    add("consent", state is RepoState.ENABLED, state.value, warn_only=True)
    if manifest.get("last_scan"):
        from prism.status import compute_status

        report = compute_status(root)
        add(
            "freshness",
            report.fresh,
            "index fresh"
            if report.fresh
            else f"{report.changed} files changed; run `prism update`",
            warn_only=True,
        )
    else:
        add("freshness", False, "no index yet; run `prism scan`", warn_only=True)

    tampered = []
    for rel, digest in manifest.get("artifacts", {}).items():
        path = root / AICONTEXT / rel
        if not path.is_file():
            tampered.append(f"{rel} (missing)")
        elif text_hash(path.read_text(encoding="utf-8")) != digest:
            tampered.append(rel)
    add(
        "artifacts",
        not tampered,
        "match the manifest"
        if not tampered
        else "changed outside PRISM: " + ", ".join(tampered[:5]),
        warn_only=True,
    )

    from prism.integrations import all_integrations

    for integration in all_integrations():
        for name, ok, detail in integration.status(root):
            add(name, ok, detail, warn_only=True)
    try:
        import mcp  # noqa: F401

        add("mcp sdk", True, "installed")
    except ImportError:
        add("mcp sdk", False, "the `mcp` package is missing; `prism mcp` will not start")

    from prism.integrations.common import SKILL_NAMES, skill_text

    stale_skills = [
        n
        for n in SKILL_NAMES
        if (root / ".claude" / "skills" / n / "SKILL.md").is_file()
        and (root / ".claude" / "skills" / n / "SKILL.md").read_text(encoding="utf-8")
        != skill_text(n)
    ]
    if stale_skills:
        add(
            "skills",
            None,
            "outdated: " + ", ".join(stale_skills) + " (run `prism init` to refresh)",
            warn_only=True,
        )

    from prism.health.git_intel import git_head

    add(
        "git",
        git_head(root) is not None,
        "history available" if git_head(root) else "no git history (churn/co-change disabled)",
        warn_only=True,
    )

    languages = manifest.get("stats", {}).get("languages", {})
    from prism.parsing.base_parser import get_parser

    unparsed = sorted(lang for lang in languages if get_parser(lang) is None)
    fixable = [lang for lang in unparsed if lang in ("javascript", "typescript", "go", "java")]
    if fixable:
        add(
            "languages",
            None,
            "no parser for " + ", ".join(fixable) + ": `pip install prism-ctx[treesitter]`",
            warn_only=True,
        )
    else:
        parsed = sorted(lang for lang in languages if lang not in unparsed)
        note = f" (counted, not parsed: {', '.join(unparsed)})" if unparsed else ""
        add("languages", True, (", ".join(parsed) or "none") + note)

    dist = Path(__file__).resolve().parent / "viewer_dist" / "index.html"
    add(
        "viewer bundle",
        dist.is_file(),
        "present" if dist.is_file() else "missing: `prism view` and HTML export unavailable",
        warn_only=True,
    )

    stray = list((root / AICONTEXT).rglob(".*.tmp"))
    if stray:
        add(
            "temp files",
            None,
            f"{len(stray)} leftover temp files (removed on next update)",
            warn_only=True,
        )
    log = root / AICONTEXT / "cache" / "hook.log"
    if log.is_file() and log.stat().st_size:
        tail = log.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-1:]
        add("hook log", None, f"recent hook error: {tail[0][:160]}" if tail else "", warn_only=True)
    return checks


# --- migrate ---------------------------------------------------------------------------------

Migration = Callable[[Path, dict[str, Any]], dict[str, Any]]

# schema_version -> migration to the next version. Empty while 1.0 is the only schema.
MIGRATIONS: dict[str, tuple[str, Migration]] = {}


def migrate(root: Path) -> dict[str, Any]:
    """Upgrade `.aicontext/` to the current schema, then rebuild every artifact.

    Narrative sections, audit findings, and decisions are preserved; generated
    artifacts are simply regenerated by a full scan.
    """
    manifest = load_manifest(root)
    if manifest is None:
        raise UserError("PRISM is not initialized in this repo.")
    start = str(manifest.get("schema_version", "1.0"))
    version = start
    steps = []
    while version != SCHEMA_VERSION:
        if version not in MIGRATIONS:
            raise UserError(
                f"no migration from schema {version} to {SCHEMA_VERSION}; run `prism scan --full`"
            )
        nxt, fn = MIGRATIONS[version]
        manifest = fn(root, manifest)
        steps.append(f"{version} -> {nxt}")
        version = nxt
    manifest["schema_version"] = SCHEMA_VERSION
    write_manifest(root, manifest)
    from prism.lifecycle import scan

    scan(root, full=True)
    return {
        "from": start,
        "to": SCHEMA_VERSION,
        "steps": steps,
        "rebuilt": True,
        "prism_version": __version__,
    }


# --- watch -----------------------------------------------------------------------------------


def watch(
    root: Path,
    interval: float = 1.0,
    on_update: Callable[[Any], None] | None = None,
    stop: Callable[[], bool] | None = None,
) -> None:
    """Poll for changes and run `update` (for editors/agents without hooks). Ctrl+C stops."""
    from prism.lifecycle import update

    manifest = load_manifest(root)
    if manifest is None:
        raise UserError("PRISM is not initialized in this repo.")
    while stop is None or not stop():
        manifest = load_manifest(root) or manifest
        state = repo_state(root, manifest.get("repo_id"))
        if state is RepoState.NOT_ENABLED:
            raise NotEnabledError(
                "PRISM is not enabled for you in this repo; run `prism enable` first."
            )
        if state is RepoState.ENABLED:
            result = update(root)
            if not result.skipped and on_update is not None:
                on_update(result)
        time.sleep(interval)
