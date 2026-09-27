"""`prism refresh prepare|commit`: keep narrative sections current with bounded effort.

`prepare` gives the host agent exactly what it needs per stale section: the
current text, what changed structurally since it was written, compact facts
for the symbols involved, and a token limit. `commit` validates the agent's
text (length, no markers, whole brief within budget), writes it into the
narrative region, and resets that section's drift.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from prism.core.errors import NotEnabledError, NotFoundError, UserError
from prism.core.markers import parse_regions
from prism.core.paths import AICONTEXT
from prism.core.tokens import estimate_tokens
from prism.drift import reset_section
from prism.navigator.store import IndexStore
from prism.writers.agents_md import BRIEF_TOKEN_LIMIT, NARRATIVE_PLACEHOLDER, NARRATIVE_SECTIONS
from prism.writers.manifest import load_manifest, now_iso, text_hash, write_manifest
from prism.writers.narrative import write_narrative

SECTION_LIMITS = {"purpose": 80, "architecture": 220, "conventions": 150}
MODULE_LIMIT = 300
MAX_FACTS = 8

GUIDANCE = {
    "purpose": "What the project does and for whom, in 2-3 sentences.",
    "architecture": "Main components, how a request/data flows through them, where state lives.",
    "conventions": "Patterns to follow (errors, naming, layering, testing) and traps to avoid.",
    "module": "What the module is responsible for, key entry points, what depends on it, what not to do in it.",
}


def _limit(section: str) -> int:
    return MODULE_LIMIT if section.startswith("modules/") else SECTION_LIMITS[section]


def _file_and_region(root: Path, section: str) -> tuple[Path, str]:
    out = root / AICONTEXT
    if section in NARRATIVE_SECTIONS:
        return out / "AGENTS.md", section
    if section.startswith("modules/"):
        return out / "modules" / f"{section.split('/', 1)[1]}.md", "summary"
    raise UserError(
        f"unknown section '{section}'; use one of {', '.join(NARRATIVE_SECTIONS)} or modules/<name>"
    )


def _current(root: Path, section: str) -> str:
    path, region = _file_and_region(root, section)
    if not path.is_file():
        raise NotFoundError(f"no file for section '{section}'")
    regions = parse_regions(path.read_text(encoding="utf-8"))
    body = regions.get(("narrative", region))
    text = body.body if body else ""
    return "" if text.strip() == NARRATIVE_PLACEHOLDER else text


def _facts_for(store: IndexStore, ids: list[str]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for i in ids:
        sym = store.symbol(i)
        if sym:
            facts.append(
                {
                    "id": sym.id,
                    "signature": sym.signature,
                    "file": sym.file,
                    "lines": [sym.start, sym.end],
                    "doc": sym.doc,
                }
            )
            continue
        mod = store.module(i)
        if mod:
            facts.append(
                {
                    "id": mod.id,
                    "file": mod.file,
                    "doc": mod.doc,
                    "imports": store.imports_of(mod.id)[:8],
                    "imported_by": store.importers_of(mod.id)[:8],
                }
            )
        if len(facts) >= MAX_FACTS:
            break
    return facts


def all_sections(root: Path) -> list[str]:
    modules_dir = root / AICONTEXT / "modules"
    mods = (
        sorted(f"modules/{p.stem}" for p in modules_dir.glob("*.md"))
        if modules_dir.is_dir()
        else []
    )
    return [*NARRATIVE_SECTIONS, *mods]


def refresh_prepare(root: Path, sections: list[str] | None = None) -> dict[str, Any]:
    manifest = load_manifest(root)
    if manifest is None:
        raise NotEnabledError("PRISM is not initialized in this repo.")
    drift = manifest.get("drift", {}).get("sections", {})
    if sections:
        chosen = sections
    else:
        chosen = sorted(k for k, v in drift.items() if v.get("stale"))
        # Unwritten AGENTS.md sections are always worth offering.
        for name in NARRATIVE_SECTIONS:
            if name not in chosen and not _current(root, name):
                chosen.append(name)
    store = IndexStore.open(root)
    try:
        packets = []
        for section in chosen:
            _file_and_region(root, section)  # validates the name
            state = drift.get(section, {})
            packet: dict[str, Any] = {
                "section": section,
                "stale": bool(state.get("stale")),
                "score": int(state.get("score", 0)),
                "token_limit": _limit(section),
                "guidance": GUIDANCE["module" if section.startswith("modules/") else section],
                "current_text": _current(root, section),
                "changes": state.get("changes", []),
                "facts": _facts_for(store, list(state.get("ids", []))),
            }
            if section.startswith("modules/"):
                path, _ = _file_and_region(root, section)
                regions = parse_regions(path.read_text(encoding="utf-8"))
                facts = regions.get(("generated", "facts"))
                packet["module_facts"] = facts.body if facts else ""
            elif section in ("architecture", "purpose"):
                packet["top_modules"] = [
                    {"id": m.id, "doc": m.doc}
                    for m in sorted(store.modules(), key=lambda m: (-m.rank, m.id))[:8]
                ]
            packets.append(packet)
    finally:
        store.close()
    return {
        "sections": packets,
        "brief_token_limit": BRIEF_TOKEN_LIMIT,
        "commit_with": "prism refresh commit <section> --file <path>",
    }


def refresh_commit(root: Path, section: str, text: str) -> dict[str, Any]:
    manifest = load_manifest(root)
    if manifest is None:
        raise NotEnabledError("PRISM is not initialized in this repo.")
    path, region = _file_and_region(root, section)
    body = text.strip()
    problems: list[str] = []
    if not body:
        problems.append("text is empty")
    if "<!--" in body or "-->" in body:
        problems.append("text must not contain HTML comments or prism markers")
    if body.startswith("#"):
        problems.append("do not include a heading; the section already has one")
    tokens = estimate_tokens(body)
    limit = _limit(section)
    if tokens > limit:
        problems.append(f"text is ~{tokens} tokens; the limit for '{section}' is {limit}")
    if not problems and section in NARRATIVE_SECTIONS:
        from prism.writers.narrative import replace_narrative

        whole = replace_narrative(
            path.read_text(encoding="utf-8").replace("\r\n", "\n"), region, body
        )
        total = estimate_tokens(whole)
        if total > BRIEF_TOKEN_LIMIT:
            problems.append(
                f"AGENTS.md would be ~{total} tokens (limit {BRIEF_TOKEN_LIMIT}); shorten by ~{total - BRIEF_TOKEN_LIMIT}"
            )
    if problems:
        raise UserError("refresh rejected: " + "; ".join(problems), problems=problems)

    new_text = write_narrative(path, region, body)
    rel = path.relative_to(root / AICONTEXT).as_posix()
    manifest = dict(manifest)
    manifest["artifacts"] = {**manifest.get("artifacts", {}), rel: text_hash(new_text)}
    manifest["drift"] = reset_section(manifest.get("drift", {}), section, now_iso())
    write_manifest(root, manifest)
    return {"section": section, "tokens": tokens, "written": rel, "drift_reset": True}
