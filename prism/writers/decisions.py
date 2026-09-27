"""`.aicontext/decisions/`: ADR-style notes the host agent (or a person) records.

Decisions are short, dated, and searchable (`prism search` indexes them), so a
future session can learn *why* the code is the way it is without anyone
re-explaining it.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from prism.core.errors import NotFoundError, UserError
from prism.core.paths import AICONTEXT
from prism.core.tokens import estimate_tokens
from prism.writers.json_writer import write_text
from prism.writers.manifest import load_manifest, text_hash, write_manifest

STATUSES = ("proposed", "accepted", "superseded", "deprecated")
MAX_TOKENS = 600
_HEADER = re.compile(r"^- (\w+): (.*)$", re.MULTILINE)


def decisions_dir(root: Path) -> Path:
    return root / AICONTEXT / "decisions"


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48] or "decision"


def parse_decision(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    first = text.splitlines()[0] if text else ""
    title = first.split(":", 1)[1].strip() if ":" in first else first.lstrip("# ").strip()
    meta = dict(_HEADER.findall(text.split("\n## ", 1)[0]))
    return {
        "id": path.stem.split("-", 1)[0],
        "title": title,
        "status": meta.get("status", "accepted"),
        "date": meta.get("date"),
        "symbols": [s.strip(" `") for s in meta.get("symbols", "").split(",") if s.strip()],
        "file": path.relative_to(path.parents[2]).as_posix()
        if len(path.parents) > 2
        else path.name,
        "text": text,
    }


def list_decisions(root: Path) -> list[dict[str, Any]]:
    directory = decisions_dir(root)
    if not directory.is_dir():
        return []
    return [parse_decision(p) for p in sorted(directory.glob("[0-9][0-9][0-9][0-9]-*.md"))]


def get_decision(root: Path, ident: str) -> dict[str, Any]:
    for d in list_decisions(root):
        if d["id"] == ident.zfill(4) or d["id"] == ident:
            return d
    raise NotFoundError(
        f"no decision '{ident}'", suggestions=[d["id"] for d in list_decisions(root)]
    )


def add_decision(
    root: Path,
    title: str,
    context: str,
    decision: str,
    consequences: str = "",
    status: str = "accepted",
    symbols: list[str] | None = None,
    supersedes: str | None = None,
) -> dict[str, Any]:
    manifest = load_manifest(root)
    if manifest is None:
        raise UserError("PRISM is not initialized in this repo.")
    title = " ".join(title.split())
    if len(title) < 5:
        raise UserError("a decision needs a descriptive title")
    if status not in STATUSES:
        raise UserError(f"status must be one of {', '.join(STATUSES)}")
    if not context.strip() or not decision.strip():
        raise UserError("a decision needs both context and the decision itself")
    existing = list_decisions(root)
    number = max((int(d["id"]) for d in existing), default=0) + 1
    ident = f"{number:04d}"
    header = [
        f"# {ident}: {title}",
        "",
        f"- status: {status}",
        f"- date: {date.today().isoformat()}",
    ]
    if symbols:
        header.append(f"- symbols: {', '.join(f'`{s}`' for s in symbols)}")
    if supersedes:
        header.append(f"- supersedes: {supersedes.zfill(4)}")
    body = [*header, "", "## Context", "", context.strip(), "", "## Decision", "", decision.strip()]
    if consequences.strip():
        body += ["", "## Consequences", "", consequences.strip()]
    text = "\n".join(body) + "\n"
    if estimate_tokens(text) > MAX_TOKENS:
        raise UserError(f"decision is ~{estimate_tokens(text)} tokens; keep it under {MAX_TOKENS}")
    path = decisions_dir(root) / f"{ident}-{_slug(title)}.md"
    write_text(path, text)
    artifacts = dict(manifest.get("artifacts", {}))
    artifacts[f"decisions/{path.name}"] = text_hash(text)
    if supersedes:
        old = get_decision(root, supersedes)
        old_path = root / AICONTEXT / old["file"].split(f"{AICONTEXT}/", 1)[-1]
        if old_path.is_file():
            updated = re.sub(
                r"^- status: \w+$", "- status: superseded", old["text"], count=1, flags=re.MULTILINE
            )
            write_text(old_path, updated)
            artifacts[f"decisions/{old_path.name}"] = text_hash(updated)
    manifest["artifacts"] = dict(sorted(artifacts.items()))
    write_manifest(root, manifest)
    return {"id": ident, "file": path.relative_to(root).as_posix(), "title": title}
