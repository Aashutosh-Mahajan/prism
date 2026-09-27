"""`prism mcp`: stdio MCP server exposing the navigator (and audit/refresh) as tools.

Every tool is a thin wrapper over the same library function the CLI calls.
Errors are returned as structured dicts (`not_enabled`, `index_missing`,
`ambiguous_target`, `not_found`, ...) instead of raised, so the agent can
recover. If PRISM is not enabled for this user, or paused, only
`prism_status` is exposed.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from prism import __version__
from prism.consent import RepoState, repo_state
from prism.core.errors import PrismError
from prism.navigator import api as nav
from prism.navigator.store import IndexStore
from prism.status import compute_status
from prism.writers.manifest import load_manifest

INSTRUCTIONS = (
    "PRISM indexes this repository. Call prism_brief once, then prism_search / prism_locate "
    "to find code and prism_context for a budgeted read list. Read only the listed line ranges. "
    "Call prism_impact before changing a public symbol."
)


class PrismTools:
    """Tool implementations bound to one repo, keeping the index open between calls."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._store: IndexStore | None = None

    def store(self) -> IndexStore:
        if self._store is None or not self._store.is_current():
            if self._store is not None:
                self._store.close()
            self._store = IndexStore.open(self.root)
        return self._store

    def call(self, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            return fn()
        except PrismError as exc:
            return exc.to_dict()

    # Each method below is exposed as an MCP tool of the same name.

    def prism_status(self) -> dict[str, Any]:
        """Enable state, index freshness, changed files, drift, stale sections, audit summary."""
        return self.call(lambda: compute_status(self.root).to_dict())

    def prism_brief(self) -> dict[str, Any]:
        """The project brief (AGENTS.md) plus a one-line freshness status."""
        return self.call(lambda: nav.op_brief(self.root))

    def prism_search(self, query: str, limit: int = 10, semantic: bool = False) -> dict[str, Any]:
        """Ranked search over symbol names, ids, docstrings, paths, routes, and decisions.

        `semantic=true` blends in local embeddings when the optional extra and model are installed.
        """
        return self.call(lambda: nav.op_search(self.store(), query, limit, semantic=semantic))

    def prism_locate(self, name: str) -> dict[str, Any]:
        """Resolve a name to candidate symbols/files with exact file:lines."""
        return self.call(lambda: nav.op_locate(self.store(), name))

    def prism_context(
        self, target: str, budget: int = 2000, depth: int = 1, with_source: bool = False
    ) -> dict[str, Any]:
        """Context pack for a symbol id, file, file:line, module, or route ("GET /orders")."""
        return self.call(
            lambda: nav.op_context(
                self.store(), target, budget=budget, depth=depth, with_source=with_source
            )
        )

    def prism_impact(self, target: str, depth: int = 3) -> dict[str, Any]:
        """What could break if the target changes, by distance, plus tests to run."""
        return self.call(lambda: nav.op_impact(self.store(), target, depth))

    def prism_module(self, name: str) -> dict[str, Any]:
        """Module summary from .aicontext/modules/."""
        return self.call(lambda: nav.op_module(self.store(), name))

    # --- narrator and auditor (the only tools that write, and only inside .aicontext/) ---

    def prism_refresh_prepare(self, sections: list[str] | None = None) -> dict[str, Any]:
        """Refresh packet per stale (or requested) AGENTS.md / module section."""
        from prism.narrator import refresh_prepare

        return self.call(lambda: refresh_prepare(self.root, sections))

    def prism_refresh_commit(self, section: str, text: str) -> dict[str, Any]:
        """Validate and write one narrative section; resets its drift on success."""
        from prism.narrator import refresh_commit

        return self.call(lambda: refresh_commit(self.root, section, text))

    def prism_audit_plan(
        self, scope: str = "all", since: str | None = None, depth: str = "standard"
    ) -> dict[str, Any]:
        """Prioritized audit plan: toolchain, targets, smells, dead code, untested, re-verify."""
        from prism.audit import build_plan

        return self.call(lambda: build_plan(self.root, scope=scope, since=since, depth=depth))

    def prism_audit_record(self, finding: dict[str, Any]) -> dict[str, Any]:
        """Record one finding. Returns its id and whether it was new, a duplicate, or reopened."""
        from prism.audit import record_finding

        return self.call(lambda: record_finding(self.root, finding))

    def prism_audit_update(self, id: str, status: str) -> dict[str, Any]:
        """Set a finding's status: open | fixed | wontfix | false_positive."""
        from prism.audit import update_status

        return self.call(lambda: update_status(self.root, id, status))

    def prism_audit_report(self) -> dict[str, Any]:
        """Render audit/REPORT.md and return summary counts (new / fixed / persisting)."""
        from prism.audit import build_report

        return self.call(lambda: build_report(self.root))

    def prism_decisions(self) -> dict[str, Any]:
        """Recorded architecture decisions (id, title, status, date, related symbols)."""
        from prism.writers.decisions import list_decisions

        return self.call(
            lambda: {
                "decisions": [
                    {k: v for k, v in d.items() if k != "text"} for d in list_decisions(self.root)
                ]
            }
        )

    def prism_decision_record(
        self,
        title: str,
        context: str,
        decision: str,
        consequences: str = "",
        symbols: list[str] | None = None,
        supersedes: str | None = None,
    ) -> dict[str, Any]:
        """Record an architecture decision in .aicontext/decisions/ (only when the user asks)."""
        from prism.writers.decisions import add_decision

        return self.call(
            lambda: add_decision(
                self.root, title, context, decision, consequences, "accepted", symbols, supersedes
            )
        )

    def prism_graph_view_url(self, focus: str | None = None, depth: int = 2) -> dict[str, Any]:
        """URL of the local graph viewer (focused on a target if given), if the user has it running."""
        from prism.viewer.server import running_viewer

        info = running_viewer(self.root)
        if info is None:
            return {
                "running": False,
                "hint": "The graph viewer is not running. Ask the user to run `prism view` "
                + (f"(or `prism view --focus {focus}`)" if focus else "")
                + "; do not start it yourself.",
            }
        params = {
            "token": info["token"],
            **({"focus": focus, "depth": str(depth)} if focus else {}),
        }
        return {"running": True, "url": f"http://127.0.0.1:{info['port']}/?{urlencode(params)}"}


NAVIGATION_TOOLS = (
    "prism_brief",
    "prism_search",
    "prism_locate",
    "prism_context",
    "prism_impact",
    "prism_module",
)
EXTRA_TOOLS: list[str] = [
    "prism_refresh_prepare",
    "prism_refresh_commit",
    "prism_audit_plan",
    "prism_audit_record",
    "prism_audit_update",
    "prism_audit_report",
    "prism_graph_view_url",
    "prism_decisions",
    "prism_decision_record",
]


def enabled_tools(root: Path) -> list[str]:
    manifest = load_manifest(root)
    state = repo_state(root, manifest.get("repo_id") if manifest else None)
    if state is not RepoState.ENABLED:
        return ["prism_status"]
    return ["prism_status", *NAVIGATION_TOOLS, *EXTRA_TOOLS]


def _server_class() -> Any:
    """MCP SDK 2.x `MCPServer`, or 1.x `FastMCP` (same decorator/run API for our use)."""
    try:
        return importlib.import_module("mcp.server.mcpserver").MCPServer
    except ImportError:  # pragma: no cover - SDK 1.x
        return importlib.import_module("mcp.server.fastmcp").FastMCP


def build_server(root: Path) -> Any:
    server_cls = _server_class()
    tools = PrismTools(root)
    try:
        server = server_cls("prism", instructions=INSTRUCTIONS, version=__version__)
    except TypeError:  # pragma: no cover - SDK without a version argument
        server = server_cls("prism", instructions=INSTRUCTIONS)
    for name in enabled_tools(tools.root):
        server.tool(name=name)(getattr(tools, name))
    return server


def run(root: Path) -> None:
    build_server(root).run("stdio")
