"""`prism hook shorten-output`: long command output, shortened before Claude reads it (opt-in).

A Claude Code `PostToolUse` hook may replace a tool's result with `updatedToolOutput`, provided
the value has the tool's own shape (for Bash: stdout, stderr, interrupted, isImage). Long test,
build, install and git output is run through the same filter as `prism filter`: failure lines and
the lines around them are always kept, passing noise is dropped, and the full output is saved
with its path at the end. Short output, and output the filter cannot shorten, is left alone.

Installed only with `prism init --shorten-output`; `PRISM_SHORTEN_OUTPUT=0` turns it off.
"""

from __future__ import annotations

import json
import os
from typing import Any

MIN_SAVED_LINES = 20  # shortening that saves less than this is not worth the changed output


def shorten_output(raw_stdin: str) -> str:
    """The hook's JSON answer, or '' to leave the tool result as it is. Never raises."""
    try:
        if os.environ.get("PRISM_SHORTEN_OUTPUT") == "0":
            return ""
        from prism.consent import RepoState
        from prism.hooks.runner import _root_from, _state, parse_payload

        payload = parse_payload(raw_stdin)
        if payload.get("tool_name") != "Bash":
            return ""
        response: Any = payload.get("tool_response")
        tool_input: Any = payload.get("tool_input")
        if not isinstance(response, dict) or not isinstance(tool_input, dict):
            return ""
        stdout, stderr = response.get("stdout"), response.get("stderr")
        command = tool_input.get("command")
        if (
            not isinstance(stdout, str)
            or not isinstance(stderr, str)
            or not isinstance(command, str)
        ):
            return ""
        root = _root_from(payload)
        if _state(root) is not RepoState.ENABLED:
            return ""
        from prism.outputfilter import filter_output, save_tee

        shortened = filter_output(command, stdout)
        if shortened.lines_in - shortened.lines_out < MIN_SAVED_LINES:
            return ""
        saved = save_tee(root, command, stdout)
        if saved is None:
            return ""  # never drop output that cannot be recovered
        note = (
            f"[PRISM: {shortened.lines_in - shortened.lines_out} of {shortened.lines_in} lines "
            f"omitted (failures kept); full output: {saved}]"
        )
        return json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "updatedToolOutput": {
                        "stdout": f"{shortened.text}\n{note}",
                        "stderr": stderr,
                        "interrupted": bool(response.get("interrupted", False)),
                        "isImage": bool(response.get("isImage", False)),
                    },
                }
            },
            ensure_ascii=False,
        )
    except Exception:
        return ""  # a hook must never break the agent's tool result
