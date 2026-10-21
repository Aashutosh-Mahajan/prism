"""`prism mcp`: stdio MCP server exposing the navigator (and audit/refresh) as tools.

Every tool is a thin wrapper over the same library function the CLI calls.
Errors are returned as structured dicts (`not_enabled`, `index_missing`,
`ambiguous_target`, `not_found`, ...) instead of raised, so the agent can
recover. If PRISM is not enabled for this user, or paused, only
`prism_status` is exposed.
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlencode

from prism import __version__
from prism.consent import RepoState, repo_state
from prism.core.errors import PrismError
from prism.instructions import SHORT
from prism.navigator import api as nav
from prism.navigator.freshness import refresh_if_stale
from prism.navigator.store import IndexStore
from prism.status import compute_status
from prism.writers.manifest import load_manifest

# Hosts show server instructions with the tool list and use them to decide when to call it.
# Reuse comes first: code a hook already delivered must not be fetched again.
INSTRUCTIONS = f"{SHORT} For code you don't have yet, use prism_task, not grep or reads."


class PrismTools:
    """Tool implementations bound to one repo, keeping the index open between calls."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._store: IndexStore | None = None
        self._seen: set[tuple[str, int, int]] = set()  # code the client is known to have received
        self._pending: tuple[str, set[tuple[str, int, int]]] | None = (
            None  # last reply, not yet proven delivered
        )
        # Work-log id for this server's lifetime (one agent conversation), unless a caller
        # shares an explicit session id with the hooks and CLI.
        self._worklog = f"mcp-{os.getpid()}-{id(self)}"

    def _require_consent(self) -> None:
        """Re-checked on every call: `prism disable` or `prism pause` takes effect at once, even
        in a server that was started while PRISM was still enabled."""
        from prism.consent import RepoState, repo_state
        from prism.core.errors import NotEnabledError
        from prism.writers.manifest import load_manifest

        manifest = load_manifest(self.root) or {}
        state = repo_state(self.root, manifest.get("repo_id"))
        if state is not RepoState.ENABLED:
            raise NotEnabledError(
                f"PRISM is {state.value} for you in this repo, so only prism_status answers. "
                "The user can run `prism enable` / `prism resume`; agents must not."
            )

    def store(self) -> IndexStore:
        self._require_consent()
        refresh_if_stale(self.root)  # answer from the working tree, whether or not hooks ran
        if self._store is None or not self._store.is_current():
            current = IndexStore.open(self.root)
            if self._store is not None:
                previous_files = self._store.manifest.get("files", {})
                current_files = current.manifest.get("files", {})
                self._seen.intersection_update(
                    {
                        item
                        for item in self._seen
                        if item[0] in current_files
                        and previous_files.get(item[0], {}).get("sha256")
                        == current_files[item[0]].get("sha256")
                    }
                )
                self._store.close()
            self._store = current
        return self._store

    def call(self, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        import sqlite3

        try:
            try:
                return fn()
            except sqlite3.DatabaseError as exc:
                # Contention is normal when a hook updates while MCP reads. It is
                # not corruption, and deleting live databases can split readers
                # and writers onto different files (or fail on Windows).
                from prism.navigator.database_errors import database_problem

                problem = database_problem(exc)
                if problem is not None:
                    return problem.to_dict()
                # A damaged disposable cache: drop every cache, reopen and answer once more.
                from prism.navigator.cache_db import purge_disposable_caches

                if self._store is not None:
                    self._store.close()
                    self._store = None
                purge_disposable_caches(self.root)
                return fn()
        except PrismError as exc:
            return exc.to_dict()
        except sqlite3.DatabaseError as exc:
            from prism.navigator.database_errors import IndexQueryError, database_problem

            problem = database_problem(exc) or IndexQueryError(
                "Index recovery failed; use bounded local search.", retryable=False
            )
            return problem.to_dict()

    # Each method below is exposed as an MCP tool of the same name.

    def prism_status(self) -> dict[str, Any]:
        """Enable state, index freshness, changed files, drift, stale sections, audit summary."""
        return self.call(lambda: compute_status(self.root).to_dict())

    def prism_knowledge(self, budget: int = 600) -> dict[str, Any]:
        """Inspect the bounded local project inventory, without loading source."""
        return self.call(lambda: nav.op_knowledge(self.store(), budget))

    def prism_brief(self, full: bool = False) -> dict[str, Any]:
        """The compact session brief (commands and notes) plus freshness; full=true for AGENTS.md."""
        return self.call(lambda: nav.op_brief(self.root, full=full))

    def prism_search(self, query: str, limit: int = 10, semantic: bool = False) -> dict[str, Any]:
        """Ranked search over symbol names, ids, docstrings, paths, routes, and decisions.

        `semantic=true` blends in local embeddings when the optional extra and model are installed.
        """
        return self.call(lambda: nav.op_search(self.store(), query, limit, semantic=semantic))

    def prism_locate(self, name: str) -> dict[str, Any]:
        """Resolve a name to candidate symbols/files with exact file:lines."""
        return self.call(lambda: nav.op_locate(self.store(), name))

    def prism_task(
        self,
        query: str,
        budget: int | None = None,
        repeat: bool = False,
        mode: str = "auto",
        session: str | None = None,
        detail: str = "full",
    ) -> dict[str, Any]:
        """Start here. For a request, symbol or file: the matching code with line numbers, every
        exact occurrence of the strings/names/quantities it mentions (exhaustive, so no grep),
        call sites, tests and impact. Code returned earlier in this session is referenced, not
        repeated, unless repeat=true. mode: auto, overview (map/signatures), code (edit source).
        budget is chars/4, 128-32000."""

        def retrieve() -> dict[str, Any]:
            from prism.navigator.session import load_seen, query_key, save_seen, session_id

            store = self.store()
            sid = session_id(session, self.root)
            if sid:
                seen = load_seen(self.root, sid, store.manifest, query)
            else:
                # In-process memory follows the same rule as the session file: what a reply
                # returned counts as delivered only once a *different* request arrives.
                qk = query_key(query)
                if self._pending is not None:
                    if self._pending[0] != qk:
                        self._seen |= self._pending[1]
                    self._pending = None
                seen = set(self._seen)
            committed = set(seen)
            log_id = sid or self._worklog
            pack = nav.op_task(
                store, query, budget, None if repeat else seen, mode, log_id, detail=detail
            )
            if not repeat:
                if sid:
                    save_seen(self.root, sid, seen, store.manifest, query, committed)
                else:
                    self._pending = (qk, seen - committed)
            from prism.writers.worklog import record_delivery, record_focus

            record_delivery(self.root, log_id, "mcp", True)
            record_focus(
                self.root, log_id, [b["symbol"] for b in pack["blocks"][:2] if b["symbol"]]
            )
            return pack

        result = self.call(retrieve)
        if "error" in result:
            # A failed call is not a delivery: keep it apart from the successes so a report
            # cannot credit PRISM for evidence the model never received.
            from prism.writers.worklog import record_delivery

            record_delivery(self.root, session or self._worklog, "mcp", False, str(result["error"]))
        return result

    def prism_find(
        self,
        patterns: list[str],
        regex: bool = False,
        ignore_case: bool = False,
        glob: list[str] | None = None,
        budget: int = 1500,
    ) -> dict[str, Any]:
        """Several searches in one call (substring, or regex), grouped by file within a budget."""
        from prism.navigator.find import run_find

        return self.call(lambda: run_find(self.store(), patterns, regex, ignore_case, glob, budget))

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

    def prism_recall(self, query: str | None = None, limit: int = 3) -> dict[str, Any]:
        """What earlier sessions asked, edited and noted (most recent first, or matching query)."""
        from prism.navigator.recall import recall

        return self.call(lambda: recall(self.root, query, limit, exclude=self._worklog))

    def prism_note(self, text: str, session: str | None = None) -> dict[str, Any]:
        """Leave a one-line handoff for the next session: what changed, what is left."""
        from prism.writers.worklog import record_note

        return self.call(lambda: record_note(self.root, session or self._worklog, text))

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

    def prism_decisions(
        self, query: str | None = None, expand_id: str | None = None, limit: int = 10
    ) -> dict[str, Any]:
        """Recorded architecture decisions (id, title, status, date, related symbols)."""
        from prism.writers.decisions import list_decisions

        self._require_consent()
        if query is not None or expand_id is not None:
            from prism.navigator.decision_memory import search_decisions

            return self.call(lambda: search_decisions(self.root, query or "", limit, expand_id))

        return self.call(
            lambda: {
                "decisions": [
                    {k: v for k, v in d.items() if k != "text"} for d in list_decisions(self.root)
                ]
            }
        )

    def prism_trace(
        self, source: str, target: str, depth: int = 4, max_nodes: int = 128
    ) -> dict[str, Any]:
        """Directed static path between symbols/modules, with provenance and explicit limits."""
        from prism.navigator.trace import trace_path

        return self.call(lambda: trace_path(self.store(), source, target, depth, max_nodes))

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


# Every tool schema is sent to the model on every turn in most agents, so the default profile
# is the few tools a coding task needs. `prism_task` also resolves names and free text, which is
# what `prism_search` and `prism_locate` are for; audit, refresh and decision tools are reached
# through the CLI and their skills, or by choosing the full profile.
LEAN_TOOLS = ("prism_task",)
STANDARD_TOOLS = ("prism_task", "prism_find", "prism_context", "prism_impact")
NAVIGATION_TOOLS = (
    "prism_brief",
    "prism_task",
    "prism_find",
    "prism_search",
    "prism_locate",
    "prism_context",
    "prism_impact",
    "prism_module",
)
EXTRA_TOOLS: list[str] = [
    "prism_knowledge",
    "prism_refresh_prepare",
    "prism_refresh_commit",
    "prism_audit_plan",
    "prism_audit_record",
    "prism_audit_update",
    "prism_audit_report",
    "prism_graph_view_url",
    "prism_trace",
    "prism_decisions",
    "prism_decision_record",
    "prism_recall",
    "prism_note",
]
PROFILES = ("lean", "standard", "full")


def resolve_profile(profile: str | None = None) -> str:
    """`lean` unless `full` is asked for (argument, else PRISM_MCP_PROFILE)."""
    chosen = (profile or os.environ.get("PRISM_MCP_PROFILE") or "lean").lower()
    return chosen if chosen in PROFILES else "lean"


def enabled_tools(root: Path, profile: str | None = None) -> list[str]:
    manifest = load_manifest(root)
    state = repo_state(root, manifest.get("repo_id") if manifest else None)
    if state is not RepoState.ENABLED:
        return ["prism_status"]
    if resolve_profile(profile) == "full":
        return ["prism_status", *NAVIGATION_TOOLS, *EXTRA_TOOLS]
    if resolve_profile(profile) == "standard":
        return ["prism_status", *STANDARD_TOOLS]
    # Lean: every tool's schema is re-sent on each model call, so an enabled repo gets one tool.
    return list(LEAN_TOOLS)


# The one tool a coding task starts with is listed upfront; the rest stay deferred.
ALWAYS_LOAD = frozenset({"prism_task"})
# Tools that only write inside .aicontext/ (never source); every other tool only reads.
WRITING_TOOLS = frozenset(
    {
        "prism_note",
        "prism_refresh_commit",
        "prism_audit_record",
        "prism_audit_update",
        "prism_audit_report",
        "prism_decision_record",
    }
)


def _annotations(name: str) -> Any:
    """Hints that let a host run read-only lookups without asking the user each time."""
    try:
        from mcp.types import ToolAnnotations
    except ImportError:  # pragma: no cover - SDK before annotations
        return None
    writes = name in WRITING_TOOLS
    return ToolAnnotations.model_validate(
        {
            "readOnlyHint": not writes,
            "destructiveHint": False,
            "idempotentHint": not writes or name == "prism_audit_update",
            "openWorldHint": False,
        }
    )


def compact_result(payload: dict[str, Any]) -> Any:
    """One compact JSON copy of a tool's answer.

    SDKs serialise a returned dict as indented text *and* again as `structuredContent`; a host
    that forwards both makes the model pay for the answer more than twice."""
    import json

    from mcp.types import CallToolResult, TextContent

    return CallToolResult.model_validate(
        {
            "content": [
                TextContent(
                    type="text",
                    text=json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
                )
            ],
            "isError": bool(payload.get("error")),
        }
    )


def _compact(method: Callable[..., dict[str, Any]]) -> Callable[..., Any]:
    import functools

    @functools.wraps(method)  # keeps the signature and docstring the SDK builds the schema from
    def handler(*args: Any, **kwargs: Any) -> Any:
        return compact_result(method(*args, **kwargs))

    handler.__annotations__ = {**method.__annotations__, "return": Any}
    return handler


def _register(server: Any, name: str, handler: Callable[..., Any]) -> None:
    """Register without a derived output schema (handlers return a finished result)."""
    options: dict[str, Any] = {"name": name, "structured_output": False}
    annotations = _annotations(name)
    if annotations is not None:
        options["annotations"] = annotations
    if name in ALWAYS_LOAD:
        # Claude Code otherwise hides MCP tools behind ToolSearch: one extra model call,
        # re-sending the whole context, before the first lookup.
        options["meta"] = {"anthropic/alwaysLoad": True}
    while True:
        try:
            server.tool(**options)(handler)
            return
        except TypeError:  # pragma: no cover - older SDK without one of the options
            if "meta" in options:
                options.pop("meta")
            elif "annotations" in options:
                options.pop("annotations")
            elif "structured_output" in options:
                options.pop("structured_output")
            else:
                raise


def _server_class() -> Any:
    """MCP SDK 2.x `MCPServer`, or 1.x `FastMCP` (same decorator/run API for our use)."""
    try:
        return importlib.import_module("mcp.server.mcpserver").MCPServer
    except ImportError:  # pragma: no cover - SDK 1.x
        return importlib.import_module("mcp.server.fastmcp").FastMCP


def build_server(root: Path, profile: str | None = None) -> Any:
    server_cls = _server_class()
    tools = PrismTools(root)
    try:
        server = server_cls("prism", instructions=INSTRUCTIONS, version=__version__)
    except TypeError:  # pragma: no cover - SDK without a version argument
        server = server_cls("prism", instructions=INSTRUCTIONS)

    def task(
        query: str,
        budget: int | None = None,
        repeat: bool = False,
        mode: str = "auto",
        session: str | None = None,
        format: Literal["compact", "json"] = "compact",
        detail: Literal["full", "brief"] = "full",
    ) -> Any:
        """Start here for any question about or change to this repo's code.

        One call: relevant source with line numbers, every exact match of named strings and
        values (no grep), callers, tests, and a checked patch for mechanical edits. Earlier
        code is referenced, not resent. Read only ranges listed as missing.
        """
        from prism.navigator.task_pack import render_task

        pack = tools.prism_task(query, budget, repeat, mode, session, detail)
        if format == "json" or pack.get("error"):
            return compact_result(pack)
        return render_task(pack)

    for name in enabled_tools(tools.root, profile):
        # Every handler returns finished text or a ready result: an SDK that derives an
        # output schema from its annotation would reject the ready result (Python 3.10).
        if name == "prism_task":
            _register(server, name, task)
        else:
            _register(server, name, _compact(getattr(tools, name)))

    def brief_resource() -> str:
        """Compact project brief: layout, commands, conventions and freshness."""

        def read() -> dict[str, Any]:
            tools._require_consent()
            return nav.op_brief(tools.root)

        answer = tools.call(read)
        if "error" in answer:
            return str(answer.get("message") or answer["error"])
        return f"{answer['brief']}\n\n{answer['freshness']}".strip()

    # Resources cost nothing until a host reads them, unlike a tool schema sent every turn.
    if hasattr(server, "resource"):
        server.resource("prism://brief", name="prism_brief", mime_type="text/markdown")(
            brief_resource
        )
    return server


def run(root: Path, profile: str | None = None) -> None:
    build_server(root, profile).run("stdio")
