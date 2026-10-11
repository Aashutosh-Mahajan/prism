"""Experimental, opt-in direct-dependent hints after source edits."""

from __future__ import annotations

import re
from pathlib import Path


def post_edit_hint(raw: str) -> str:
    from prism.config import load_config
    from prism.consent import RepoState
    from prism.core.tokens import estimate_tokens
    from prism.hooks.runner import _root_from, _state, edited_paths, parse_payload, session_of
    from prism.navigator.store import IndexStore
    from prism.writers.worklog import _digest, _read, worklog_dir

    payload = parse_payload(raw)
    root = _root_from(payload)
    if (
        _state(root) is not RepoState.ENABLED
        or load_config(root).extra.get("post_edit_hints", False) is not True
    ):
        return ""
    session = session_of(payload)
    if not session:
        return ""
    log = _read(worklog_dir(root) / (_digest(session) + ".jsonl"))
    touched = set(log.edits) if log else set()
    changed = set()
    for value in edited_paths(payload):
        path = Path(value)
        try:
            changed.add(
                (path if path.is_absolute() else root / path)
                .resolve()
                .relative_to(root.resolve())
                .as_posix()
            )
        except ValueError:
            continue
    touched.update(changed)
    if not changed:
        return ""
    store = IndexStore.open(root)
    try:
        candidates = set()
        for file in sorted(changed):
            for symbol in store.symbols_in_file(file):
                anchors = {
                    word.lower()
                    for word in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|[0-9]+", symbol.name)
                    if len(word) >= 3
                }
                if not anchors:
                    continue
                for link in store.callers(symbol.id):
                    if (
                        link.symbol.file in touched
                        or (
                            getattr(link, "resolution", None)
                            or ("name" if link.confidence == "low" else "resolved")
                        )
                        != "resolved"
                    ):
                        continue
                    path = (root / link.symbol.file).resolve()
                    if not path.is_relative_to(root.resolve()):
                        continue
                    try:
                        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                    except OSError:
                        continue
                    line = link.line or link.symbol.start
                    words = (
                        set(re.findall(r"[a-z0-9]+", lines[line - 1].lower()))
                        if 0 < line <= len(lines)
                        else set()
                    )
                    # Lexical confirmation anchored to the changed callee; theta=0.5.
                    if (
                        sum(any(anchor in word for word in words) for anchor in anchors)
                        / len(anchors)
                        < 0.5
                    ):
                        continue
                    candidates.add((link.symbol.file, line, link.symbol.name))
        output = "Untouched direct callers (index evidence; check whether this edit applies):"
        for file, line, name in sorted(candidates)[:10]:
            addition = f"\n{file}:{line} {name}"
            if estimate_tokens(output + addition) > 150:
                break
            output += addition
        return output if "\n" in output else ""
    finally:
        store.close()
