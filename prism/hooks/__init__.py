"""Load only the hook requested by the native host."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from prism.hooks.prompt import user_prompt
    from prism.hooks.runner import post_edit, session_start

__all__ = ["post_edit", "session_start", "user_prompt"]


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(name)
    from importlib import import_module

    module = "prism.hooks.prompt" if name == "user_prompt" else "prism.hooks.runner"
    return getattr(import_module(module), name)
