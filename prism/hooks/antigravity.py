"""Antigravity `PreInvocation` hook: the packet for the user's request arrives with the request.

Antigravity runs a `PreInvocation` hook before every model call and lets it inject steps. The hook
receives the conversation id, the workspace paths and the path of the transcript, whose latest
`USER_INPUT` entry holds the request inside `<USER_REQUEST>` tags. This module turns that into the
same packet the other agents' prompt hooks add, injected once per user request as a `userMessage`
(an `ephemeralMessage` is dropped after the first model call, so it would be lost).

Output is always one JSON object, `{}` when there is nothing to add, and the hook never raises.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_REQUEST = re.compile(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", re.S)
STATE_FILE = "antigravity-hook.json"
MAX_REMEMBERED = 50


def latest_request(transcript: Path) -> tuple[int, str] | None:
    """(step index, text) of the newest user request in an Antigravity transcript."""
    found: tuple[int, str] | None = None
    try:
        with transcript.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(entry, dict) or entry.get("type") != "USER_INPUT":
                    continue
                # Steps a hook injects are recorded as USER_INPUT too (source SYSTEM_SDK, wrapped
                # in <USER_REQUEST>): only what the person typed is a request to answer.
                if entry.get("source", "USER_EXPLICIT") != "USER_EXPLICIT":
                    continue
                content = str(entry.get("content") or "")
                match = _REQUEST.search(content)
                text = (match.group(1) if match else content).strip()
                if text:
                    found = (int(entry.get("step_index") or 0), text)
    except OSError:
        return None
    return found


def _state_path(root: Path) -> Path:
    from prism.consent import cache_root

    return cache_root(root) / STATE_FILE


HOOK_SECONDS = 12.0  # Antigravity allows 20 s per hook; a slow first answer beats none
MAX_EMPTY_ATTEMPTS = 2  # a silent hook (warming caches, a greeting) is retried once, not forever


def _attempts(root: Path, key: str) -> int:
    try:
        state = json.loads(_state_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    return int(state.get(key, 0)) if isinstance(state, dict) else 0


def _remember(root: Path, key: str, value: int) -> None:
    path = _state_path(root)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            state = {}
    except (OSError, ValueError):
        state = {}
    state[key] = value
    for old in list(state)[:-MAX_REMEMBERED]:
        del state[old]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        pass  # the worst case is one repeated, still-correct injection


def pre_invocation(raw_stdin: str) -> str:
    """The hook's stdout: `{"injectSteps": [{"userMessage": ...}]}` or `{}`."""
    try:
        from prism.hooks import user_prompt
        from prism.hooks.runner import parse_payload

        payload = parse_payload(raw_stdin)
        workspaces = payload.get("workspacePaths")
        transcript = payload.get("transcriptPath")
        conversation = str(payload.get("conversationId") or "")
        if not (isinstance(workspaces, list) and workspaces and isinstance(transcript, str)):
            return "{}"
        request = latest_request(Path(transcript))
        if request is None:
            return "{}"
        step, text = request
        from prism.hooks.runner import _root_from

        root = _root_from({"cwd": str(workspaces[0])})
        key = f"{conversation}:{step}"
        tried = _attempts(root, key)
        if tried >= MAX_EMPTY_ATTEMPTS:
            return "{}"  # injected already, or twice found nothing worth adding
        packet = user_prompt(
            json.dumps({"cwd": str(workspaces[0]), "session_id": conversation, "prompt": text}),
            time_budget=HOOK_SECONDS,
            inline_build=True,
        )
        if not packet.strip():
            _remember(root, key, tried + 1)
            return "{}"
        _remember(root, key, MAX_EMPTY_ATTEMPTS)
        # The stop gate only checks requests that changed a value found by an exhaustive list.
        from prism.hooks.gate import is_value_change

        _remember(root, f"lit:{key}", 1 if is_value_change(packet) else 0)
        return json.dumps({"injectSteps": [{"userMessage": packet}]}, ensure_ascii=False)
    except BaseException:
        return "{}"


MAX_GATE_PASSES = 1


def stop_gate(raw_stdin: str) -> str:
    """The `Stop` hook: before the agent finishes a value change, list sites that still match.

    The agent is about to stop, so a clean answer costs nothing: the hook stays silent. Only when
    the old value is still present in the indexed source does it send the agent back, once per
    request, with the exact remaining lines. This protects correctness; it does not cut tokens.
    """
    try:
        from prism.hooks.runner import _root_from, _state, parse_payload

        payload = parse_payload(raw_stdin)
        workspaces = payload.get("workspacePaths")
        transcript = payload.get("transcriptPath")
        conversation = str(payload.get("conversationId") or "")
        if not (isinstance(workspaces, list) and workspaces and isinstance(transcript, str)):
            return "{}"
        request = latest_request(Path(transcript))
        if request is None:
            return "{}"
        step, text = request
        root = _root_from({"cwd": str(workspaces[0])})
        from prism.consent import RepoState

        if _state(root) is not RepoState.ENABLED:
            return "{}"
        key = f"{conversation}:{step}"
        if _attempts(root, f"lit:{key}") != 1 or _attempts(root, f"gate:{key}") >= MAX_GATE_PASSES:
            return "{}"
        from prism.hooks.gate import remaining_sites

        remaining = remaining_sites(root, text)
        if remaining is None:
            return "{}"
        _remember(root, f"gate:{key}", MAX_GATE_PASSES)
        return json.dumps(
            {
                "decision": "continue",
                "reason": "PRISM verify before you finish:\n" + remaining,
            },
            ensure_ascii=False,
        )
    except BaseException:
        return "{}"


def render(out: Any) -> str:
    return out if isinstance(out, str) and out else "{}"
