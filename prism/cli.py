"""`prism` command-line interface. Thin wrappers over library functions."""

from __future__ import annotations

import contextlib
import json
import os
import sys
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Annotated, Any, TypeVar

import typer
from rich.console import Console

from prism import __version__
from prism.consent import RepoState
from prism.core.errors import EXIT_INTERNAL, PrismError, UserError
from prism.core.paths import AICONTEXT, find_repo_root

app = typer.Typer(
    name="prism",
    help="PRISM: a persistent, local context layer for AI coding agents.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)
hook_app = typer.Typer(help="Entry points for host-agent hooks (read hook JSON on stdin).")
refresh_app = typer.Typer(help="Keep AGENTS.md and module summaries current (prism-refresh skill).")
app.add_typer(hook_app, name="hook")
audit_app = typer.Typer(help="Agent-driven codebase audit (prism-audit skill).")
app.add_typer(refresh_app, name="refresh")
app.add_typer(audit_app, name="audit")

out = Console(highlight=False)
err = Console(stderr=True, highlight=False)

F = TypeVar("F", bound=Callable[..., Any])

RootOption = Annotated[
    Path | None,
    typer.Option("--root", help="Repository root (default: detected from the current directory)."),
]
JsonOption = Annotated[bool, typer.Option("--json", help="Machine-readable output.")]
QuietOption = Annotated[
    bool, typer.Option("--quiet", "-q", help="No output unless there is an error.")
]


def emit(text: str) -> None:
    """Plain output: never interpreted as Rich markup."""
    typer.echo(text)


def emit_json(data: Any) -> None:
    typer.echo(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True))


def _output(data: dict[str, Any], as_json: bool, renderer: Callable[[dict[str, Any]], str]) -> None:
    if as_json:
        emit_json(data)
    else:
        emit(renderer(data))


def _root(root: Path | None) -> Path:
    return (root or find_repo_root(Path.cwd())).resolve()


def handle_errors(fn: F) -> F:
    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except typer.Exit:
            raise
        except PrismError as exc:
            if kwargs.get("as_json"):
                emit_json(exc.to_dict())
            else:
                err.print(f"[red]error:[/red] {exc}", markup=True, highlight=False)
                for key in ("candidates", "suggestions", "problems"):
                    for v in (exc.details.get(key) or [])[:10]:
                        err.print(f"  {v['id'] if isinstance(v, dict) else v}", markup=False)
            raise typer.Exit(exc.exit_code) from exc
        except Exception as exc:
            err.print(f"[red]internal error:[/red] {type(exc).__name__}: {exc}")
            raise typer.Exit(EXIT_INTERNAL) from exc

    return wrapper  # type: ignore[return-value]


def _version_callback(value: bool) -> None:
    if value:
        out.print(f"prism {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version."),
    ] = False,
) -> None:
    """PRISM maps a codebase once and keeps the map fresh for coding agents."""


# --- setup and consent ---------------------------------------------------------


@app.command()
@handle_errors
def init(
    root: RootOption = None,
    agent: Annotated[
        str, typer.Option("--agent", help="claude-code | cursor | codex | generic | auto | none")
    ] = "auto",
    hooks: Annotated[bool | None, typer.Option("--hooks/--no-hooks", help="Agent hooks.")] = None,
    mcp: Annotated[
        bool | None, typer.Option("--mcp/--no-mcp", help="Register the MCP server.")
    ] = None,
    git_hooks: Annotated[
        bool | None,
        typer.Option("--git-hooks/--no-git-hooks", help="Git post-commit/merge/checkout hooks."),
    ] = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip prompts (scripted use).")] = False,
    run_scan: Annotated[
        bool | None,
        typer.Option("--scan/--no-scan", help="Run the initial scan without asking."),
    ] = None,
) -> None:
    """Enable PRISM in this repo. Shows every change first and asks before making it."""
    from prism.integrations import IntegrationOptions, detect_agents
    from prism.integrations.git_hooks import hooks_dir
    from prism.lifecycle import apply_init, plan_init, scan

    repo = _root(root)
    if agent == "none":
        agents: list[str] = []
    elif agent == "auto":
        agents = detect_agents(repo)
    else:
        agents = [agent]

    def ask(question: str, current: bool | None, relevant: bool) -> bool:
        if not relevant:
            return False
        if current is not None:
            return current
        return True if yes else typer.confirm(question, default=True)

    options = IntegrationOptions(
        hooks=ask(
            "Install agent hooks (session brief + index update after edits)?",
            hooks,
            "claude-code" in agents,
        ),
        mcp=ask(
            "Register the PRISM MCP server for your agent?",
            mcp,
            bool({"claude-code", "cursor"} & set(agents)),
        ),
    )
    use_git_hooks = ask(
        "Install git hooks (update the index after commit/merge/checkout)?",
        git_hooks,
        hooks_dir(repo) is not None,
    )
    plan = plan_init(repo, agents, options, use_git_hooks)
    if plan.is_noop:
        out.print(f"PRISM is already initialized and enabled in {repo.as_posix()}.")
    else:
        out.print(f"PRISM will make these changes in [bold]{repo.as_posix()}[/bold]:")
        for change in plan.changes:
            out.print(f"  {change.kind:<8} {change.target}  [dim]({change.detail})[/dim]")
        if not yes and not typer.confirm("Proceed?", default=True):
            out.print("Nothing changed.")
            raise typer.Exit(0)
        apply_init(plan)
        out.print("[green]PRISM initialized.[/green]")

    do_scan = (
        run_scan
        if run_scan is not None
        else (True if yes else typer.confirm("Run the initial scan now?", default=True))
    )
    if do_scan:
        _print_scan(scan(repo), as_json=False)
    else:
        out.print("Run `prism scan` when you're ready to build the index.")


@app.command("uninstall-integration")
@handle_errors
def uninstall_integration(
    root: RootOption = None,
    purge: Annotated[
        bool, typer.Option("--purge", help="Also delete .aicontext/ and your consent flag.")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y")] = False,
) -> None:
    """Remove every PRISM-managed block, hook, MCP entry, and skill (restoring backups)."""
    from prism.lifecycle import apply_uninstall, plan_uninstall

    repo = _root(root)
    removals = plan_uninstall(repo)
    if not removals and not purge:
        out.print("No PRISM integration files found.")
        return
    for change in removals:
        out.print(f"  remove   {change.path}  [dim]({change.detail})[/dim]")
    if purge:
        out.print(
            f"  delete   {AICONTEXT}/  [dim](the whole index, including audit findings)[/dim]"
        )
    if not yes and not typer.confirm("Proceed?", default=False):
        out.print("Nothing changed.")
        raise typer.Exit(0)
    apply_uninstall(repo, removals, purge=purge)
    out.print("PRISM integration removed." + (" Index deleted." if purge else ""))


@app.command()
@handle_errors
def install(
    global_: Annotated[
        bool, typer.Option("--global", help="Required: user-level agent note.")
    ] = False,
    suggest: Annotated[
        bool, typer.Option("--suggest", help="Let agents mention PRISM once in large repos.")
    ] = False,
) -> None:
    """Add a short user-level note to your agent's global instructions (opt-in)."""
    from prism.integrations.global_note import install_global

    if not global_:
        raise UserError("use `prism install --global`; per-repo setup is `prism init`")
    changed = install_global(suggest)
    for path in changed:
        out.print(f"updated {path}")
    if not changed:
        out.print("Global note already installed.")


@app.command()
@handle_errors
def uninstall(
    global_: Annotated[
        bool, typer.Option("--global", help="Required: remove the user-level note.")
    ] = False,
) -> None:
    """Remove the user-level note added by `prism install --global`."""
    from prism.integrations.global_note import uninstall_global

    if not global_:
        raise UserError(
            "use `prism uninstall --global`; per-repo removal is `prism uninstall-integration`"
        )
    changed = uninstall_global()
    for path in changed:
        out.print(f"updated {path}")
    if not changed:
        out.print("No global note found.")


@app.command()
@handle_errors
def enable(root: RootOption = None) -> None:
    """Enable PRISM for you in this repo (local flag, never committed)."""
    from prism.lifecycle import set_enabled

    set_enabled(_root(root), True)
    out.print("PRISM enabled for you in this repo.")


@app.command()
@handle_errors
def disable(root: RootOption = None) -> None:
    """Disable PRISM for you in this repo. Nothing in the repo changes."""
    from prism.lifecycle import set_enabled

    set_enabled(_root(root), False)
    out.print("PRISM disabled for you in this repo.")


@app.command()
@handle_errors
def pause(root: RootOption = None) -> None:
    """Stop all automatic PRISM activity in this repo without removing anything."""
    from prism.lifecycle import set_paused

    set_paused(_root(root), True)
    out.print("PRISM paused. Hooks are no-ops until `prism resume`.")


@app.command()
@handle_errors
def resume(root: RootOption = None) -> None:
    """Resume automatic PRISM activity after `prism pause`."""
    from prism.lifecycle import set_paused

    set_paused(_root(root), False)
    out.print("PRISM resumed.")


# --- index -----------------------------------------------------------------------


def _print_scan(manifest: dict[str, Any], as_json: bool) -> None:
    stats = manifest.get("stats", {})
    if as_json:
        emit_json({"stats": stats, "last_scan": manifest.get("last_scan")})
        return
    out.print(
        f"Indexed {stats.get('files', 0)} files · {stats.get('symbols', 0)} symbols · "
        f"{stats.get('import_edges', 0)} import edges · {stats.get('call_edges', 0)} call edges"
        + (
            f" · [yellow]{stats['parse_errors']} parse errors[/yellow]"
            if stats.get("parse_errors")
            else ""
        )
    )


@app.command("scan")
@handle_errors
def scan_cmd(
    root: RootOption = None,
    full: Annotated[bool, typer.Option("--full", help="Ignore cached hashes and parses.")] = False,
    as_json: JsonOption = False,
) -> None:
    """Build the full index into .aicontext/."""
    from prism.lifecycle import scan

    _print_scan(scan(_root(root), full=full), as_json)


@app.command("update")
@handle_errors
def update_cmd(
    files: Annotated[
        list[str] | None, typer.Option("--files", help="Files known to have changed.")
    ] = None,
    root: RootOption = None,
    quiet: QuietOption = False,
    as_json: JsonOption = False,
) -> None:
    """Incrementally update the index: re-parse only changed files."""
    from prism.lifecycle import update

    result = update(_root(root), files=files)
    data = {
        "skipped": result.skipped,
        "changed": list(result.changed),
        "added": list(result.added),
        "deleted": list(result.deleted),
        "reparsed": result.reparsed,
        "rank_approx": bool(result.manifest.get("rank_approx")),
    }
    if as_json:
        emit_json(data)
    elif not quiet:
        if result.skipped:
            emit("Index already up to date.")
        else:
            emit(
                f"Updated: {len(result.changed)} changed, {len(result.added)} added, "
                f"{len(result.deleted)} deleted · {result.reparsed} re-parsed"
            )


def _status_line(report: Any) -> str:
    if report.state is RepoState.NOT_INITIALIZED:
        return "not initialized"
    if not report.indexed:
        return f"{report.state.value} · no index yet (run `prism scan`)"
    fresh = "index fresh" if report.fresh else f"{report.changed} files changed since last update"
    return f"{report.state.value} · {fresh}"


@app.command()
@handle_errors
def status(root: RootOption = None, as_json: JsonOption = False) -> None:
    """Show consent state, index freshness, drift, and audit summary."""
    from prism.status import compute_status

    report = compute_status(_root(root))
    if as_json:
        emit_json(report.to_dict())
        return
    out.print(_status_line(report))
    if report.indexed:
        s = report.stats
        out.print(
            f"last update {report.last_scan} · {s.get('files', 0)} files · "
            f"{s.get('symbols', 0)} symbols · {s.get('test_files', 0)} test files"
        )
    for label, items in (
        ("added", report.added),
        ("modified", report.modified),
        ("deleted", report.deleted),
    ):
        for path in items[:10]:
            out.print(f"  {label:<8} {path}")
        if len(items) > 10:
            out.print(f"  … and {len(items) - 10} more {label}")
    if report.stale_sections:
        out.print(
            "stale sections: " + ", ".join(report.stale_sections) + " (run the prism-refresh skill)"
        )
    if report.audit:
        a = report.audit
        out.print(
            f"audit: {a['open']} open findings"
            + (f" · last report {a['last_report']}" if a.get("last_report") else "")
        )


# --- navigator -------------------------------------------------------------------

BudgetOption = Annotated[int, typer.Option("--budget", min=100, help="Token budget for the pack.")]


def _store(root: Path | None) -> Any:
    from prism.navigator.store import IndexStore

    return IndexStore.open(_root(root))


@app.command()
@handle_errors
def brief(root: RootOption = None, as_json: JsonOption = False) -> None:
    """Print .aicontext/AGENTS.md plus a one-line freshness status."""
    from prism.navigator import api as nav
    from prism.navigator import render

    _output(nav.op_brief(_root(root)), as_json, render.render_brief)


@app.command("locate")
@handle_errors
def locate_cmd(
    name: Annotated[str, typer.Argument(help="Symbol, qualified suffix, module, or file name.")],
    root: RootOption = None,
    limit: Annotated[int, typer.Option("--limit", min=1)] = 10,
    as_json: JsonOption = False,
) -> None:
    """Resolve a name to candidates with file:lines (exact → suffix → fuzzy)."""
    from prism.navigator import api as nav
    from prism.navigator import render

    _output(nav.op_locate(_store(root), name, limit), as_json, render.render_locate)


@app.command()
@handle_errors
def context(
    target: Annotated[str, typer.Argument(help="Symbol id, file, file:line, module, or route.")],
    root: RootOption = None,
    budget: BudgetOption = 2000,
    depth: Annotated[int, typer.Option("--depth", min=1, max=2)] = 1,
    with_source: Annotated[
        bool, typer.Option("--with-source", help="Inline the target body.")
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Build a context pack: location, callers, callees, tests, risk, and a read list."""
    from prism.navigator import api as nav
    from prism.navigator import render

    data = nav.op_context(_store(root), target, budget=budget, depth=depth, with_source=with_source)
    _output(data, as_json, render.render_context)


@app.command("impact")
@handle_errors
def impact_cmd(
    target: Annotated[str, typer.Argument(help="Symbol id, file, file:line, module, or route.")],
    root: RootOption = None,
    depth: Annotated[int, typer.Option("--depth", min=1, max=6)] = 3,
    as_json: JsonOption = False,
) -> None:
    """Blast radius: what could break if the target changes, and which tests to run."""
    from prism.navigator import api as nav
    from prism.navigator import render

    _output(nav.op_impact(_store(root), target, depth), as_json, render.render_impact)


@app.command()
@handle_errors
def search(
    query: Annotated[str, typer.Argument(help="Free text: names, docstrings, paths, routes.")],
    root: RootOption = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 10,
    semantic: Annotated[
        bool,
        typer.Option("--semantic", help="Blend in local embeddings (needs prism-ctx\\[semantic])."),
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Ranked free-text search over the index (BM25, fully local)."""
    from prism.navigator import api as nav
    from prism.navigator import render

    _output(
        nav.op_search(_store(root), query, limit, semantic=semantic), as_json, render.render_search
    )


@app.command()
@handle_errors
def module(
    name: Annotated[str, typer.Argument(help="Module or package name.")],
    root: RootOption = None,
    as_json: JsonOption = False,
) -> None:
    """Show a module summary from .aicontext/modules/."""
    from prism.navigator import api as nav

    _output(nav.op_module(_store(root), name), as_json, lambda d: str(d["text"]).rstrip())


# --- narrator ----------------------------------------------------------------------


@refresh_app.command("prepare")
@handle_errors
def refresh_prepare_cmd(
    sections: Annotated[
        list[str] | None, typer.Option("--sections", help="Sections to prepare.")
    ] = None,
    root: RootOption = None,
) -> None:
    """Emit the refresh packet (JSON) for stale or requested sections."""
    from prism.narrator import refresh_prepare

    emit_json(refresh_prepare(_root(root), sections))


@refresh_app.command("commit")
@handle_errors
def refresh_commit_cmd(
    section: Annotated[
        str, typer.Argument(help="purpose | architecture | conventions | modules/<name>")
    ],
    file: Annotated[Path, typer.Option("--file", help="Markdown file with the new section text.")],
    root: RootOption = None,
    as_json: JsonOption = False,
) -> None:
    """Validate and write one narrative section, resetting its drift."""
    from prism.narrator import refresh_commit

    text = file.read_text(encoding="utf-8")
    result = refresh_commit(_root(root), section, text)
    if as_json:
        emit_json(result)
    else:
        emit(f"Refreshed '{section}' (~{result['tokens']} tokens); drift reset.")


# --- auditor -----------------------------------------------------------------------


@audit_app.command("plan")
@handle_errors
def audit_plan_cmd(
    scope: Annotated[str, typer.Option("--scope", help="all | changed | <path>")] = "all",
    since: Annotated[
        str | None, typer.Option("--since", help="Git ref for --scope changed.")
    ] = None,
    depth: Annotated[str, typer.Option("--depth", help="quick | standard | deep")] = "standard",
    root: RootOption = None,
    as_json: JsonOption = False,
) -> None:
    """Write audit/audit_plan.json: toolchain, prioritized targets, smells, and more."""
    from prism.audit import build_plan

    plan = build_plan(_root(root), scope=scope, since=since, depth=depth)
    if as_json:
        emit_json(plan)
        return
    emit(f"Audit plan written to {AICONTEXT}/audit/audit_plan.json")
    emit(
        f"scope {scope} · depth {depth} · {len(plan['targets'])} targets · {len(plan['smells'])} smells · "
        f"{len(plan['untested'])} untested · {len(plan['reverify'])} to re-verify"
    )
    for t in plan["toolchain"]:
        emit(f"  {t['kind']:<9} {t['command']}  ({t['detected_from']})")
    for t in plan["targets"][:10]:
        emit(f"  {t['score']:>6.2f}  {t['target']}  — {'; '.join(t['reasons'][:3])}")


@audit_app.command("record")
@handle_errors
def audit_record_cmd(
    json_file: Annotated[str, typer.Option("--json", help="Finding JSON file, or '-' for stdin.")],
    root: RootOption = None,
) -> None:
    """Validate and record one finding (or a JSON list of findings)."""
    from prism.audit import record_finding

    raw = sys.stdin.read() if json_file == "-" else Path(json_file).read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise UserError(f"finding is not valid JSON: {exc}") from exc
    items = data if isinstance(data, list) else [data]
    results = [record_finding(_root(root), item) for item in items]
    emit_json(results if isinstance(data, list) else results[0])


@audit_app.command("update")
@handle_errors
def audit_update_cmd(
    finding_id: Annotated[str, typer.Argument(help="Finding id, e.g. F-012.")],
    status_: Annotated[
        str, typer.Option("--status", help="open | fixed | wontfix | false_positive")
    ],
    note: Annotated[str | None, typer.Option("--note")] = None,
    root: RootOption = None,
    as_json: JsonOption = False,
) -> None:
    """Change a finding's lifecycle status."""
    from prism.audit import update_status

    result = update_status(_root(root), finding_id, status_, note)
    if as_json:
        emit_json(result)
    else:
        emit(f"{finding_id} is now {result['status']}.")


@audit_app.command("report")
@handle_errors
def audit_report_cmd(root: RootOption = None, as_json: JsonOption = False) -> None:
    """Render audit/REPORT.md (with new/fixed/persisting vs. the last audit) and archive it."""
    from prism.audit import build_report

    result = build_report(_root(root))
    if as_json:
        emit_json(result)
    else:
        sev = ", ".join(f"{n} {s}" for s, n in result["open_by_severity"].items()) or "none"
        emit(
            f"{result['report']}: {result['open']} open ({sev}) · {len(result['new'])} new · "
            f"{len(result['fixed'])} fixed · {len(result['persisting'])} persisting"
        )


# --- visualizer --------------------------------------------------------------------

graph_app = typer.Typer(help="Export the code graph (HTML, Obsidian, Mermaid, DOT, GraphML, JSON).")
app.add_typer(graph_app, name="graph")


@app.command()
@handle_errors
def view(
    root: RootOption = None,
    focus: Annotated[
        str | None, typer.Option("--focus", help="Open on the local graph of a target.")
    ] = None,
    depth: Annotated[int, typer.Option("--depth", min=1, max=4)] = 2,
    port: Annotated[
        int, typer.Option("--port", help="Port on 127.0.0.1 (default: random free port).")
    ] = 0,
    no_open: Annotated[
        bool, typer.Option("--no-open", help="Print the URL instead of opening a browser.")
    ] = False,
) -> None:
    """Open the interactive code graph in your browser (local server on 127.0.0.1)."""
    import webbrowser

    from prism.viewer.server import ViewerServer

    server = ViewerServer(_root(root), port=port)
    url = server.url(focus, depth if focus else None)
    emit(f"PRISM graph: {url}")
    emit("Press Ctrl+C to stop.")
    if not no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        emit("Stopped.")


@graph_app.command("export")
@handle_errors
def graph_export(
    html: Annotated[Path | None, typer.Option("--html", help="Self-contained HTML file.")] = None,
    obsidian: Annotated[
        Path | None, typer.Option("--obsidian", help="Obsidian vault directory.")
    ] = None,
    mermaid: Annotated[
        bool, typer.Option("--mermaid", help="Mermaid diagram (stdout or --out).")
    ] = False,
    dot: Annotated[bool, typer.Option("--dot", help="Graphviz DOT (stdout or --out).")] = False,
    graphml: Annotated[bool, typer.Option("--graphml", help="GraphML for Gephi/yEd.")] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Nodes and edges as JSON.")] = False,
    around: Annotated[
        str | None, typer.Option("--around", help="Only the neighbourhood of a target.")
    ] = None,
    depth: Annotated[int, typer.Option("--depth", min=1, max=4)] = 1,
    level: Annotated[str, typer.Option("--level", help="package | file | symbol")] = "file",
    layer: Annotated[
        str, typer.Option("--layer", help="import | call | tests | cochange")
    ] = "import",
    symbols: Annotated[
        bool, typer.Option("--symbols", help="HTML/Obsidian: include symbol-level nodes.")
    ] = False,
    graph_colors: Annotated[
        bool, typer.Option("--with-graph-colors", help="Obsidian: add risk color groups.")
    ] = False,
    out: Annotated[Path | None, typer.Option("--out", help="Output file for text formats.")] = None,
    root: RootOption = None,
) -> None:
    """Export the graph. Exactly one format flag is required."""
    chosen = [
        name
        for name, on in (
            ("html", html),
            ("obsidian", obsidian),
            ("mermaid", mermaid),
            ("dot", dot),
            ("graphml", graphml),
            ("json", as_json),
        )
        if on
    ]
    if len(chosen) != 1:
        raise UserError(
            "choose exactly one of --html, --obsidian, --mermaid, --dot, --graphml, --json"
        )
    repo = _root(root)
    if html is not None:
        from prism.writers.graph_export import export_html

        result = export_html(repo, html, include_symbols=symbols)
        emit(
            f"Wrote {result['path']} ({result['bytes'] / 1_000_000:.2f} MB); open it in any browser, offline."
        )
        return
    if obsidian is not None:
        from prism.writers.obsidian import export_obsidian

        result = export_obsidian(repo, obsidian, include_symbols=symbols, graph_colors=graph_colors)
        emit(
            f"Wrote {result['notes']} notes to {obsidian} ({result['removed']} stale notes removed)."
        )
        return
    from prism.writers.graph_export import export_diagram

    text = export_diagram(
        repo, chosen[0], out, level=level, layer=layer, around=around, depth=depth
    )
    if out is None:
        typer.echo(text, nl=False)
    else:
        emit(f"Wrote {out}")


# --- decisions and maintenance -------------------------------------------------------

decision_app = typer.Typer(
    help="Architecture decisions in .aicontext/decisions/ (prism-decisions skill)."
)
app.add_typer(decision_app, name="decision")


@decision_app.command("add")
@handle_errors
def decision_add(
    title: Annotated[str, typer.Option("--title", help="Short statement of the decision.")],
    context: Annotated[str, typer.Option("--context", help="The problem and forces at play.")],
    decision: Annotated[str, typer.Option("--decision", help="What was decided, and why.")],
    consequences: Annotated[
        str, typer.Option("--consequences", help="Trade-offs and follow-ups.")
    ] = "",
    status_: Annotated[
        str, typer.Option("--status", help="proposed | accepted | superseded | deprecated")
    ] = "accepted",
    symbols: Annotated[
        list[str] | None, typer.Option("--symbol", help="Related symbol id (repeatable).")
    ] = None,
    supersedes: Annotated[
        str | None, typer.Option("--supersedes", help="Id of a decision this replaces.")
    ] = None,
    root: RootOption = None,
) -> None:
    """Record an architecture decision."""
    from prism.writers.decisions import add_decision

    result = add_decision(
        _root(root), title, context, decision, consequences, status_, symbols, supersedes
    )
    emit(f"Recorded decision {result['id']}: {result['title']} ({result['file']})")


@decision_app.command("list")
@handle_errors
def decision_list(root: RootOption = None, as_json: JsonOption = False) -> None:
    """List recorded decisions."""
    from prism.writers.decisions import list_decisions

    items = [{k: v for k, v in d.items() if k != "text"} for d in list_decisions(_root(root))]
    if as_json:
        emit_json({"decisions": items})
        return
    if not items:
        emit("No decisions recorded yet.")
    for d in items:
        emit(f"{d['id']}  [{d['status']}]  {d['title']}  ({d['date']})")


@decision_app.command("show")
@handle_errors
def decision_show(
    ident: Annotated[str, typer.Argument(help="Decision id, e.g. 0003.")], root: RootOption = None
) -> None:
    """Print one decision."""
    from prism.writers.decisions import get_decision

    emit(get_decision(_root(root), ident)["text"].rstrip())


@app.command()
@handle_errors
def watch(
    root: RootOption = None,
    interval: Annotated[
        float, typer.Option("--interval", min=0.2, help="Seconds between checks.")
    ] = 1.0,
) -> None:
    """Keep the index fresh while you work (for editors/agents without hooks). Ctrl+C stops."""
    from prism.maintenance import watch as run_watch

    repo = _root(root)
    emit(f"Watching {repo.as_posix()} (Ctrl+C to stop)…")

    def report(result: Any) -> None:
        emit(
            f"updated: {len(result.changed)} changed, {len(result.added)} added, {len(result.deleted)} deleted"
        )

    try:
        run_watch(repo, interval=interval, on_update=report)
    except KeyboardInterrupt:
        emit("Stopped.")


@app.command()
@handle_errors
def doctor(root: RootOption = None, as_json: JsonOption = False) -> None:
    """Diagnose the setup: install, index, consent, hooks, MCP, git, parsers, viewer."""
    from prism.maintenance import doctor as run_doctor

    checks = run_doctor(_root(root))
    if as_json:
        emit_json({"checks": [c.to_dict() for c in checks]})
    else:
        marks = {"ok": "[green]✓[/green]", "warn": "[yellow]![/yellow]", "fail": "[red]✗[/red]"}
        for c in checks:
            out.print(f" {marks[c.status]} {c.name:<16} ", end="")
            out.print(c.detail, markup=False, highlight=False)
    if any(c.status == "fail" for c in checks):
        raise typer.Exit(1)


@app.command()
@handle_errors
def migrate(root: RootOption = None, as_json: JsonOption = False) -> None:
    """Upgrade .aicontext/ to this PRISM version's schema and rebuild the index."""
    from prism.maintenance import migrate as run_migrate

    result = run_migrate(_root(root))
    if as_json:
        emit_json(result)
    else:
        emit(
            f"Index is at schema {result['to']} (prism {result['prism_version']}); artifacts rebuilt."
        )


# --- hooks and MCP -----------------------------------------------------------------


def _read_stdin() -> str:
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return ""
        return sys.stdin.read()
    except (OSError, ValueError):
        return ""


def _hard_exit() -> None:
    """Hooks must never linger: flush and exit 0 even if a bounded update is still running."""
    with contextlib.suppress(Exception):
        sys.stdout.flush()
        sys.stderr.flush()
    if os.environ.get("PRISM_HOOK_NO_EXIT") != "1":
        os._exit(0)


@hook_app.command("session-start")
def hook_session_start() -> None:
    """Catch up on outside changes, then print the brief into the agent's context."""
    from prism.hooks import session_start

    try:
        text = session_start(_read_stdin())
        if text:
            typer.echo(text)
    finally:
        _hard_exit()


@hook_app.command("post-edit")
def hook_post_edit() -> None:
    """Update the index for the file the agent just edited. Silent; always exits 0."""
    from prism.hooks import post_edit

    try:
        post_edit(_read_stdin())
    finally:
        _hard_exit()


@app.command("mcp")
@handle_errors
def mcp_cmd(root: RootOption = None) -> None:
    """Run the MCP server over stdio (started by your agent from .mcp.json)."""
    from prism.mcp.server import run

    run(_root(root))


def main() -> None:
    # Windows consoles default to a legacy code page; PRISM output is UTF-8.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(OSError, ValueError):
                reconfigure(encoding="utf-8")
    app()
