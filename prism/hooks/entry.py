"""Command-line plumbing for host-agent hooks, kept free of typer and rich.

A hook starts a fresh Python process on every edit, so what it imports is latency the agent
waits for. `prism hook ...` is routed here by `prism.entry` before the full CLI is loaded.
"""

from __future__ import annotations

import contextlib
import os
import sys

HOOKS = ("session-start", "user-prompt", "post-edit", "pre-invocation", "stop", "dedupe-read")


def use_utf8() -> None:
    """Agents exchange UTF-8 with hooks, but a Windows pipe defaults to the locale code page, on
    which a non-Latin character raises (and the hook, which must never fail, would then print
    nothing at all). Read and write UTF-8 regardless."""
    for stream, errors in (
        (sys.stdin, "replace"),
        (sys.stdout, "replace"),
        (sys.stderr, "replace"),
    ):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(OSError, ValueError):
                reconfigure(encoding="utf-8", errors=errors)


def read_stdin() -> str:
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return ""
        return sys.stdin.read()
    except (OSError, ValueError):
        return ""


def hard_exit() -> None:
    """Hooks must never linger: flush and exit 0 even if a bounded update is still running."""
    with contextlib.suppress(Exception):
        sys.stdout.flush()
        sys.stderr.flush()
    if os.environ.get("PRISM_HOOK_NO_EXIT") != "1":
        os._exit(0)


def background_enabled() -> bool:
    """Post-edit updates run in a detached process unless `PRISM_HOOK_SYNC=1` asks to wait."""
    return os.environ.get("PRISM_HOOK_SYNC") != "1"


_EVENT = {"session-start": "SessionStart", "user-prompt": "UserPromptSubmit"}


def parse_flags(args: list[str]) -> dict[str, str]:
    """`--format X` / `--event Y` (also `--format=X`) from a hook command line."""
    flags: dict[str, str] = {}
    pending: str | None = None
    for arg in args:
        if pending is not None:
            flags[pending] = arg
            pending = None
        elif arg in ("--format", "--event"):
            pending = arg[2:]
        elif arg.startswith(("--format=", "--event=")):
            key, _, value = arg[2:].partition("=")
            flags[key] = value
    return flags


def run_hook(name: str, args: list[str] | None = None) -> None:
    """Run one hook: read the hook JSON from stdin, act, print what belongs in the agent's
    context, and exit 0 whatever happens."""
    flags = parse_flags(args or [])
    use_utf8()
    try:
        from prism.hooks.formats import render_context

        fmt = flags.get("format", "text")
        event = flags.get("event", _EVENT.get(name, "UserPromptSubmit"))
        text = ""
        if name == "session-start":
            from prism.hooks import session_start

            text = session_start(read_stdin())
        elif name == "user-prompt":
            from prism.hooks import user_prompt

            text = user_prompt(read_stdin())
        elif name == "post-edit":
            from prism.hooks import post_edit

            post_edit(read_stdin(), background=background_enabled())
        elif name == "pre-invocation":
            # Antigravity: always one JSON object on stdout, `{}` when there is nothing to add.
            from prism.hooks.antigravity import pre_invocation

            sys.stdout.write(pre_invocation(read_stdin()) + chr(10))
            return
        elif name == "stop":
            raw = read_stdin()
            if '"workspacePaths"' in raw:  # Antigravity: always one JSON object
                from prism.hooks.antigravity import stop_gate

                sys.stdout.write(stop_gate(raw) + chr(10))
            else:  # Claude Code, Codex: a block decision, or nothing
                from prism.hooks.gate import stop

                text = stop(raw)
                if text:
                    sys.stdout.write(text + chr(10))
            return
        elif name == "dedupe-read":
            from prism.hooks.dedupe import decide

            text = decide(read_stdin())
            if text:
                sys.stdout.write(text + chr(10))
            return
        out = render_context(text, fmt, event)
        if out:
            sys.stdout.write(out if out.endswith("\n") else out + "\n")
    except BaseException:  # a hook must never break or slow the agent session
        pass
    finally:
        hard_exit()
