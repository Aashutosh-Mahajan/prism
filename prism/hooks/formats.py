"""How hook output reaches each agent's context.

Claude Code adds a hook's plain stdout to the conversation. Codex and Gemini CLI read a JSON
object with `hookSpecificOutput.additionalContext` (and Codex also accepts plain stdout, but
names the event). Cursor's `sessionStart` hook returns `additional_context`.
"""

from __future__ import annotations

import json

FORMATS = ("text", "json", "cursor")
MAX_CONTEXT_CHARS = 9500


def render_context(text: str, fmt: str, event: str) -> str:
    """`text` as the hook should print it for the agent that asked for `fmt`."""
    if not text:
        return ""
    if len(text) > MAX_CONTEXT_CHARS:
        raise ValueError("hook context exceeds 9500 characters; retrieve with a smaller budget")
    if fmt == "json":
        payload = {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}
        return json.dumps(payload, ensure_ascii=False)
    if fmt == "cursor":
        return json.dumps({"additional_context": text}, ensure_ascii=False)
    return text
