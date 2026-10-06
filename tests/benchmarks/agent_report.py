"""Render the six measured Codex runs into a reviewable Markdown report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def report(
    base: Path, destination: Path, transport: str = "cli", comparison: Path | None = None
) -> None:
    metrics = json.loads((base / "metrics.json").read_text(encoding="utf-8"))
    scores = json.loads((base / "scores.json").read_text(encoding="utf-8"))
    expected = {f"run{n}_{side}" for n in range(1, 4) for side in ("without", "with")}
    if set(metrics) != expected or set(scores) != expected:
        raise SystemExit("All six completed runs must be collected and scored first")
    if not all(row["source_integrity_passed"] for row in metrics.values()):
        raise SystemExit("An agent changed source files; review before reporting")
    if transport == "mcp":
        for run in range(1, 4):
            row = metrics[f"run{run}_with"]
            if (
                row.get("mcp_server_starts") != 1
                or not row.get("mcp_tool_calls")
                or not row.get("mcp_client_closed")
                or not row.get("mcp_server_exited")
                or row["mcp_tool_calls"] != row.get("mcp_tool_responses")
                or row.get("prism_cli_command_sites") != 0
            ):
                raise SystemExit(f"Run {run} is missing valid persistent MCP evidence")
    models = {tuple(row["models"]) for row in metrics.values()}
    efforts = {tuple(row["effort"]) for row in metrics.values()}
    if len(models) != 1 or len(efforts) != 1:
        raise SystemExit("Agent models or reasoning efforts differ")
    averages = {}
    for side in ("without", "with"):
        averages[side] = {
            field: sum(metrics[f"run{n}_{side}"][field] for n in range(1, 4)) / 3
            for field in (
                "model_turns",
                "tool_calls",
                "total_input_processed",
                "billable_input_equiv_proxy",
                "work_context",
                "tool_output_tokens_est",
                "duration_seconds",
                "first_turn_context",
            )
        }
        for field in ("correct", "partial", "tasks_with_existing_backend_tests_named"):
            averages[side][field] = sum(scores[f"run{n}_{side}"][field] for n in range(1, 4)) / 3
    changes = {
        field: (averages["with"][field] / averages["without"][field] - 1) * 100
        for field in averages["with"]
        if averages["without"][field]
    }
    modelled = json.loads((base / "modelled.json").read_text(encoding="utf-8"))[0]
    source = json.loads((base / "source-integrity.json").read_text(encoding="utf-8"))
    if not source["passed"]:
        raise SystemExit("The original source no longer matches the copied files")
    lines = [
        f"# Codex agent benchmark{' using MCP' if transport == 'mcp' else ''} — 2026-10-03",
        "",
        f"Six fresh Codex subagents completed 12 reports each, in three paired runs. "
        f"All used `{next(iter(models))[0]}` with `{next(iter(efforts))[0]}` reasoning effort.",
        "",
        f"PRISM changed average tool output by **{changes['tool_output_tokens_est']:+.1f}%**, "
        f"total input processed by **{changes['total_input_processed']:+.1f}%**, "
        f"and completion time by **{changes['duration_seconds']:+.1f}%**. "
        f"Mean primary-function scores were **{averages['with']['correct']:.2f}/12 with PRISM** "
        f"and **{averages['without']['correct']:.2f}/12 without**.",
        "",
        "These are measured agent runs. The separate modelled estimate below is not a substitute for them.",
        "",
        "## Measured results",
        "",
        "| Run | Agent | Model turns | Tool calls | Input processed | Billable proxy | Work context | Tool output estimate | Seconds | Correct /12 | Partial | Tasks naming backend tests |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    fields = (
        "model_turns",
        "tool_calls",
        "total_input_processed",
        "billable_input_equiv_proxy",
        "work_context",
        "tool_output_tokens_est",
        "duration_seconds",
        "correct",
        "partial",
        "tasks_with_existing_backend_tests_named",
    )
    for run in range(1, 4):
        for side in ("without", "with"):
            name = f"run{run}_{side}"
            row = metrics[name] | scores[name]
            values = [
                f"{row[f]:,.1f}" if f == "duration_seconds" else f"{row[f]:,}" for f in fields
            ]
            lines.append(f"| {run} | {side} | " + " | ".join(values) + " |")
    for side in ("without", "with"):
        lines.append(
            f"| **Mean** | **{side}** | "
            + " | ".join(f"{averages[side][field]:,.1f}" for field in fields)
            + " |"
        )
    if transport == "mcp":
        lines.extend(
            [
                "",
                "## MCP protocol evidence",
                "",
                "PRISM was not registered as a native Codex tool in this chat. Each PRISM agent imported a small "
                "adapter through the persistent Node tool, started the real PRISM MCP server once, and invoked its tools "
                "using MCP JSON-RPC over stdio. The server retained its index between calls. Agents did not invoke the "
                "PRISM CLI or call navigator library functions directly. Protocol logs independently record every request "
                "and response. This is a genuine MCP transport run with an adapter, not a native registered-tool run.",
                "",
                "The adapter returned one structured response representation, avoiding duplicate text and JSON copies. "
                "Source range reads remained ordinary file reads. Adapter startup, schema discovery, calls and shutdown "
                "were part of the timed agent sessions; the controller's separate smoke test was excluded.",
                "",
                "| Run | Server starts | MCP tool calls | Responses | RPC errors | Tool errors | Navigation errors | PRISM CLI command sites |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for run in range(1, 4):
            row = metrics[f"run{run}_with"]
            lines.append(
                f"| {run} | "
                + " | ".join(
                    str(row[field])
                    for field in (
                        "mcp_server_starts",
                        "mcp_tool_calls",
                        "mcp_tool_responses",
                        "mcp_protocol_errors",
                        "mcp_tool_errors",
                    )
                )
                + f" | {sum(row.get('mcp_application_errors', {}).values())} | {row['prism_cli_command_sites']} |"
            )
        lines.extend(
            [
                "",
                "Navigation errors are structured PRISM responses such as `not_found`; agents can recover "
                "with another query. Exact error codes are retained in metrics.json. Every client closed and every server exited.",
            ]
        )
        lines.extend(
            [
                "",
                "Per-tool request counts:",
                "",
                "| Run | Brief | Search | Locate | Context | Impact | Module | Status |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for run in range(1, 4):
            tools = metrics[f"run{run}_with"]["mcp_tools"]
            lines.append(
                f"| {run} | "
                + " | ".join(
                    str(tools.get("prism_" + name, 0))
                    for name in (
                        "brief",
                        "search",
                        "locate",
                        "context",
                        "impact",
                        "module",
                        "status",
                    )
                )
                + " |"
            )
    if comparison:
        old = json.loads((comparison / "averages.json").read_text(encoding="utf-8"))["averages"]
        lines.extend(
            [
                "",
                "## Comparison with the earlier CLI run",
                "",
                "Each column is an average of three agents. The MCP baseline was rerun rather than reused. "
                "This is an observational comparison: fresh agent decisions, timing, setup prompts, JSON output "
                "and adapter overhead can differ, so any change cannot be attributed solely to transport.",
                "",
                "| Metric | Earlier CLI with PRISM | New MCP with PRISM | Earlier baseline | New baseline |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for field in (
            "model_turns",
            "tool_output_tokens_est",
            "total_input_processed",
            "work_context",
            "billable_input_equiv_proxy",
            "duration_seconds",
            "correct",
        ):
            values = (
                old["with"][field],
                averages["with"][field],
                old["without"][field],
                averages["without"][field],
            )
            lines.append(f"| {field} | " + " | ".join(f"{v:,.1f}" for v in values) + " |")
    lines.extend(
        [
            "",
            "## Per-task scoring",
            "",
            "C = correct primary; P = expected function appears as a dependent; W = neither. "
            "The supplied alternatives for tasks 5, 6 and 8 were retained. No alternatives were added after seeing results.",
            "",
            "| Task | Run 1 without | Run 1 with | Run 2 without | Run 2 with | Run 3 without | Run 3 with |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for task in range(1, 13):
        grades = [
            scores[f"run{run}_{side}"]["tasks"][task - 1]["grade"][0].upper()
            for run in range(1, 4)
            for side in ("without", "with")
        ]
        lines.append(f"| {task} | " + " | ".join(grades) + " |")
    lines.extend(
        [
            "",
            "## Direct caller mentions",
            "",
            "Across the 12 target functions, the current index lists 76 direct callers. Counts below use textual name matching; "
            "full per-task caller lists and matches are retained in scores.json.",
            "",
            "| Run | Without PRISM | With PRISM |",
            "|---|---:|---:|",
        ]
    )
    for run in range(1, 4):
        lines.append(
            f"| {run} | {scores[f'run{run}_without']['direct_callers_named_count']} / 76 | "
            f"{scores[f'run{run}_with']['direct_callers_named_count']} / 76 |"
        )
    caller_means = {
        side: sum(scores[f"run{run}_{side}"]["direct_callers_named_count"] for run in range(1, 4))
        / 3
        for side in ("without", "with")
    }
    lines.append(
        f"| **Mean** | {caller_means['without']:.1f} / 76 | {caller_means['with']:.1f} / 76 |"
    )
    lines.extend(
        [
            "",
            "## Protocol and interpretation",
            "",
            f"Platforma currently indexes {modelled['files']} files and {modelled['loc']:,} lines. "
            "Each repetition used two identical fresh source copies; only the PRISM side was indexed. "
            "The consent registry was isolated per repetition. Agents received bug reports, not target names or the answer key, "
            "and had fresh histories. Both sides of each pair ran concurrently. Pair starts were dispatched sequentially within seconds; "
            "pairs could overlap as slots became available.",
            "",
            f"Source hashes passed for all six copies. The {source['copied_files_checked']} copied files were also "
            "checked against the original checkout and matched. Agents diagnosed code without modifying it or running application tests.",
            "",
            "Copy exclusions included dependencies, Git data, build/cache output, local agent configuration, secret environment "
            "files, prior Claude outputs, design-screen assets and the migration dump. These identical exclusions avoid irrelevant "
            "configuration, credentials and bulk data entering either side.",
            "",
            "The transcript metrics count native Codex model responses and tool calls, including agent status messages. A `functions.exec` "
            "or Node call can batch many shell commands or MCP requests, so tool calls are not individual searches or PRISM invocations. "
            "Input processed sums per-response `input_tokens`; "
            "Codex already includes cached input in this field. Work context is final minus first response input size. Tool output is "
            "recorded tool-result characters divided by four, an estimate that includes search output and wrappers, not only source code.",
            "",
            f"Mean initial context was {averages['without']['first_turn_context']:,.0f} tokens without and "
            f"{averages['with']['first_turn_context']:,.0f} with. The prompts differed in navigation instructions; their initial sizes "
            "are close but not exactly equal. Controller preparation, indexing, measurement and scoring are excluded from agent totals.",
            "",
            "The billable column is the plan's comparison proxy: uncached input + 1.25 × cache writes + 0.1 × cache reads. "
            "It is not an actual OpenAI invoice or a model-price claim. All observed cache-write counts were zero.",
            "",
            "Existing backend-test mentions were checked against actual test modules/classes. This measures naming an existing test, "
            "not proving that it covers the behavior; generic PRISM mappings can be weak. Detailed caller coverage in scores.json "
            "matches unqualified caller names against the complete indexed direct-caller list; it is indicative and can be ambiguous. "
            "PRISM's impact display can truncate callers, so its displayed list was not used as the denominator.",
            "",
            "Primary scoring requires the owner name for class methods, avoiding a false match between a legacy detail view's "
            "inherited get_object and RestaurantViewSet.get_object. This clarification leaves the earlier CLI scores unchanged. "
            "The fixed key penalizes plausible neighboring primaries: APICache.get instead of set (task 11), and resolvePostAuthPath "
            "instead of getPostAuthRedirectPath (task 12). These functions can be defensible investigation points. The scores measure "
            "agreement with this plan's key rather than confirmed bug fixes. Three repetitions on one repository do not establish "
            "a general performance guarantee.",
            "",
            "## Previously measured modelled estimate"
            if transport == "mcp"
            else "## Separate modelled benchmark",
            "",
            f"The existing scripted harness estimates {modelled['total_without']:,} tokens without PRISM versus "
            f"{modelled['total_with_prism']:,} with ({modelled['saving']:.1%} reduction). Its best-case baseline is "
            f"{modelled['total_without_best_case']:,} ({modelled['saving_vs_best_case']:.1%} reduction). "
            "This harness is given the target symbols and replays fixed navigation strategies; it does not measure real agent decisions.",
            "",
            "## Evidence and reproduction",
            "",
            "Raw native transcripts, final answers, current answer-key locations, hashes, metrics and detailed scores are stored under "
            f"`{base.as_posix()}/` (ignored local artifacts).",
            "",
            "```powershell",
            "python -m tests.benchmarks.agent_prepare --repo D:/Projects/Platforma/Platforma --plan C:/Users/mahaj/Downloads/agent-benchmark-plan.md --output <NEW-DIRECTORY>"
            + (" --transport mcp" if transport == "mcp" else ""),
            "# Run fresh Codex subagent pairs with the report-only prompts captured in the archived transcripts.",
            f"python -m tests.benchmarks.agent_collect --session-dir C:/Users/mahaj/.codex/sessions/2026/10/03 --parent 01a0fe60-70db-76d3-870d-344f0fc6a32d --output {base.as_posix()}"
            + (" --agent-prefix mcp_" if transport == "mcp" else ""),
            f"python -m tests.benchmarks.agent_score {base.as_posix()}",
            f"python -m tests.benchmarks.agent_report {base.as_posix()} --output {destination.as_posix()} --transport {transport}",
            "```",
            "",
            "Measurement/scoring regression tests: `python -m pytest tests/test_agent_measure.py`.",
        ]
    )
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (base / "averages.json").write_text(
        json.dumps({"averages": averages, "changes_percent": changes}, indent=2), encoding="utf-8"
    )
    print(destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--transport", choices=("cli", "mcp"), default="cli")
    parser.add_argument("--comparison", type=Path)
    args = parser.parse_args()
    report(args.base, args.output, args.transport, args.comparison)
