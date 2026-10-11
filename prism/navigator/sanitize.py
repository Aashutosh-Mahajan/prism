"""Display-only source sanitation; raw source remains available for checked edits."""

from __future__ import annotations

import re
import unicodedata
from pathlib import PurePosixPath


def strip_hidden(text: str) -> str:
    return "".join(
        character
        for character in text
        if character in "\n\r\t" or unicodedata.category(character) not in {"Cf", "Cc", "Cs"}
    )


def clean_source(text: str, file: str) -> str:
    text = strip_hidden(text)
    if PurePosixPath(file).suffix.lower() in {".md", ".markdown", ".mdx"}:
        text = re.sub(
            r"<!--.*?(?:-->|\Z)",
            lambda match: "".join(char for char in match[0] if char in "\r\n"),
            text,
            flags=re.DOTALL,
        )
    return text


def allowed_document(file: str, query: str) -> bool:
    path = PurePosixPath(file.replace("\\", "/"))
    protected = path.name.upper() in {"AGENTS.MD", "CLAUDE.MD", "SKILL.MD"} or any(
        part.lower() in {".claude", ".codex"} for part in path.parts
    )
    if not protected:
        return True
    asked = query.replace("\\", "/").lower()
    return path.as_posix().lower() in asked or path.name.lower() in asked
