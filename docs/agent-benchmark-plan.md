# Agent benchmark: with PRISM vs without PRISM

A repeatable plan for comparing two real coding agents on the same repository and the same
bug reports: one navigating with PRISM, one with its normal tools (Glob, Grep, Read). It
measures what the agents actually consume, from their transcripts, and whether answer quality
holds up.

- [Target repository](#target-repository)
- [The 12 tasks](#the-12-tasks)
- [Answer key](#answer-key)
- [Setup](#setup)
- [Agent prompts](#agent-prompts)
- [What to measure](#what-to-measure)
- [Measurement script](#measurement-script)
- [Results template](#results-template)
- [Pilot run (4 tasks, 2026-10-03)](#pilot-run-4-tasks-2026-10-03)
- [Task file for the token harness](#task-file-for-the-token-harness)

## Target repository

Platforma: Django backend + React/TypeScript frontend, about 351 files and 50,000 lines
(as of 2026-10-03). Locations in this document are from that date; re-check them with
`prism locate <name>` before scoring if the code has changed.

## The 12 tasks

Give agents **only the bug report text**. The bugs may or may not truly exist; the job is to find
the code that implements the behaviour and is where a fix would go.

| # | Bug report (what the agent sees) | Area |
|---|---|---|
| 1 | "Email verification codes are rejected as expired even right after they are sent." | Backend auth |
| 2 | "Components crash because the logged-in user is undefined outside the auth provider." | Frontend auth |
| 3 | "The OLAP cube query returns wrong totals when filtering by a dimension." | Data warehouse |
| 4 | "The restaurant detail endpoint returns 404 when the restaurant is looked up by slug." | Backend API |
| 5 | "After a restaurant accepts an order, the customer's order-tracking status doesn't advance." | Backend orders |
| 6 | "The dashboard revenue chart puts orders placed shortly before midnight into the next day's bar." | Frontend charts |
| 7 | "On the login page, when the server rejects the credentials, the form shows '[object Object]' instead of the server's error message." | Frontend errors |
| 8 | "The KPI cards' percentage change seems to compare against the wrong previous period." | Backend analytics |
| 9 | "The warehouse ETL creates duplicate dimension rows for slowly changing dimensions." | Data warehouse |
| 10 | "Simulated payments succeed even when the payment should fail." | Backend payments |
| 11 | "The API response cache keeps serving stale data after the TTL expires." | Frontend caching |
| 12 | "After signing in, users are redirected to the wrong page." | Frontend routing |

The mix is 6 backend, 6 frontend and 2 data-warehouse tasks, with targets that have between 2
and 22 callers, so both quick lookups and "touches a lot" cases are covered.

## Answer key

Keep this hidden from the agents.

| # | Expected function | Location | Callers |
|---|---|---|---:|
| 1 | `backend.core.models.EmailCode.verify` | `backend/core/models.py:243-260` | 2 |
| 2 | `frontend.zesty_app.src.contexts.AuthContext.useAuth` | `frontend/zesty-app/src/contexts/AuthContext.tsx:122-128` | 22 |
| 3 | `backend.warehouse.olap.queries.resolve` | `backend/warehouse/olap/queries.py:71-106` | 8 |
| 4 | `backend.zesty.views.RestaurantViewSet.get_object` | `backend/zesty/views.py:139-162` | 6 |
| 5 | `backend.zesty.views.OrderViewSet._sync_standard_tracking` | `backend/zesty/views.py:488-561` | 4 |
| 6 | `frontend.zesty_app.src.components.dashboard.theme.bucketByDay` | `frontend/zesty-app/src/components/dashboard/theme.ts:276-314` | 4 |
| 7 | `frontend.zesty_app.src.api.auth.parseApiError` | `frontend/zesty-app/src/api/auth.ts:36-56` | 5 |
| 8 | `backend.core.analytics.build_kpis` | `backend/core/analytics.py:126-136` | 5 |
| 9 | `backend.warehouse.etl.load._bulk_scd2_load` | `backend/warehouse/etl/load.py:127-152` | 5 |
| 10 | `backend.core.models.Payment.simulate_payment` | `backend/core/models.py:119-125` | 4 |
| 11 | `frontend.zesty_app.src.utils.cache.APICache.set` | `frontend/zesty-app/src/utils/cache.ts:46-54` | 5 |
| 12 | `frontend.zesty_app.src.utils.helpers.getPostAuthRedirectPath` | `frontend/zesty-app/src/utils/helpers.ts:72-74` | 6 |

**Also accept these.** In the pilot run, these bug reports had more than one reasonable answer:

| # | Also correct | Why |
|---|---|---|
| 5 | `backend.zesty.views.OrderViewSet.update_status` (`views.py:900-927`) | It is the code that runs when the restaurant accepts an order |
| 6 | `backend.core.analytics.grouped_by_bucket`, `backend.zesty.views.RestaurantViewSet.summary` | They do the backend day grouping, where the timezone decides the day |
| 8 | `backend.core.analytics.get_window` / `Window.previous` | They build the previous period that `build_kpis` uses |

**Scoring per task:**
- **Correct:** the primary function matches the key or an accepted alternative.
- **Partially correct:** the expected function is named as a caller or dependent, but not as the primary.
- **Wrong:** neither of the above.

Also record how many of the target's callers the agent named, and whether it found relevant tests.

## Setup

Use copies, never the real Platforma checkout, and keep PRISM's consent registry in a scratch
folder so your real settings are untouched.

```bash
BENCH=~/agentbench
mkdir -p "$BENCH/with" "$BENCH/without" "$BENCH/cfg"

# Two identical copies without dependencies, git data or build output
cd /path/to/Platforma
for d in with without; do
  tar --exclude=node_modules --exclude=.git --exclude=.venv --exclude=venv \
      --exclude=dist --exclude=build --exclude=__pycache__ -cf - . | (cd "$BENCH/$d" && tar -xf -)
done

# Index only the "with" copy
cd "$BENCH/with"
export PRISM_CONFIG_HOME="$BENCH/cfg"
prism init --yes --agent none --no-hooks --no-mcp --no-git-hooks --no-scan
prism scan
prism status        # should say: enabled · index fresh
```

Run both agents **at the same time, with the same model**, and repeat the whole run **3 times**.
Average the results, because agent behaviour varies between runs. Start each repetition from
fresh copies.

## Agent prompts

The two prompts are identical except for the tooling paragraph. Replace `<WITH>`, `<WITHOUT>`
and `<CFG>` with your absolute paths, and paste the 12 bug reports from [the tasks](#the-12-tasks)
into the TASKS section.

### Agent with PRISM

```text
You are a coding agent taking part in a benchmark. Work ONLY inside this repository copy:
<WITH>
It is a Django backend + React/TypeScript frontend web app (~50k lines).

This repository is indexed by PRISM, a local code index. Use it to navigate instead of exploring the repository:
- Every prism command must be run from the repository directory with this environment variable set, e.g. in Bash:
  cd "<WITH>" && PRISM_CONFIG_HOME="<CFG>" prism <command>
- Start by running `prism brief` once (it describes the project).
- For each task: `prism search "<words from the report>"` (or `prism locate <name>`), then `prism context <symbol id>` for the best candidate, and read ONLY the line ranges in its read list using the Read tool with offset/limit. Use `prism impact <symbol id>` to find what depends on it and which tests to run.
- If PRISM does not lead you to the answer, you may fall back to a targeted Grep, but prefer PRISM.
- Never run `prism init`, `prism scan`, `prism update`, or `prism enable`.

Rules for everyone in this benchmark:
- Do NOT edit, create or delete any files. Diagnosis only.
- Do not look outside the repository directory above. Do not use subagents.
- Be efficient: read only what you need to answer confidently.

TASKS (bug reports from users; the bug may or may not truly exist — your job is to find the code that implements the behaviour and is where a fix would go):
1. ...
12. ...

FINAL ANSWER FORMAT (exactly this, nothing else):
For each task N:
- Task N: primary function = <fully qualified name or file::function>, location = <file>:<start>-<end>
- Why: <one sentence>
- Callers/dependents to check: <list>
- Tests to run: <list or "none found">
Then a section "SELF-REPORT":
- Tool calls made: <number>
- Files read in full: <list>
- Files read partially (ranges): <list with ranges>
- prism commands run: <number>
- Grep/Glob calls: <number>
```

### Agent without PRISM

```text
You are a coding agent taking part in a benchmark. Work ONLY inside this repository copy:
<WITHOUT>
It is a Django backend + React/TypeScript frontend web app (~50k lines).

Use your normal tools (Glob, Grep, Read, and read-only Bash such as ls) to explore and understand the code, the way you usually would. Do not use any tool called `prism`.

Rules for everyone in this benchmark:
- Do NOT edit, create or delete any files. Diagnosis only.
- Do not look outside the repository directory above. Do not use subagents.
- Be efficient: read only what you need to answer confidently.

TASKS (bug reports from users; the bug may or may not truly exist — your job is to find the code that implements the behaviour and is where a fix would go):
1. ...
12. ...

FINAL ANSWER FORMAT: identical to the PRISM agent, with "prism commands run: 0".
```

## What to measure

Take these numbers from each agent's **transcript**, not from its self-report. Claude Code stores
subagent transcripts at
`~/.claude/projects/<project>/<session-id>/subagents/agent-<id>.jsonl`.

| Metric | How | Why it matters |
|---|---|---|
| Total input tokens processed | Sum over turns of input + cache writes + cache reads | Every turn re-sends the whole context; this is the real volume |
| Billable input | Uncached input + cache writes × 1.25 + cache reads × 0.1 | Approximates what you pay with prompt caching |
| Fixed overhead | Context size at the first turn | System prompt, tool definitions and the task, the same for both agents |
| Work context | Context at the last turn minus context at the first turn | What the work actually added, without the overhead |
| Model turns | Assistant messages with usage | Fewer turns means less context re-sent |
| Tool calls | `tool_use` blocks, by tool | Search effort |
| Tool output read | Characters of tool results ÷ 4 | How much code and search output entered the context |
| Time to finish | First and last transcript timestamps | Speed |
| Correct answers | Answer key above | Quality must not drop |
| Callers named, tests found | Compare with `prism impact` on the target | Completeness |

The token count shown in the agent UI is the **final context size**. It includes the fixed overhead
(about 78,000 tokens in the pilot), which hides most of the difference, so don't compare agents
on that number alone.

## Measurement script

Save as `measure.py` and run `python measure.py agent-<id1>.jsonl agent-<id2>.jsonl`.

```python
"""Summarise subagent JSONL transcripts: token usage, turns, tool calls, tool output, duration."""

import collections
import json
import sys


def summarise(path: str) -> dict:
    usage = collections.Counter()
    tools = collections.Counter()
    sizes: list[int] = []
    seen: set[str] = set()
    tool_chars = 0
    stamps: list[str] = []
    for line in open(path, encoding="utf-8"):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("timestamp"):
            stamps.append(rec["timestamp"])
        msg = rec.get("message") or {}
        if not isinstance(msg, dict):
            continue
        if rec.get("type") == "assistant":
            u = msg.get("usage") or {}
            if u and msg.get("id") not in seen:
                seen.add(msg.get("id"))
                ctx = 0
                for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
                    usage[k] += int(u.get(k) or 0)
                    ctx += int(u.get(k) or 0)
                sizes.append(ctx)
            for block in msg.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tools[block.get("name")] += 1
        if rec.get("type") == "user":
            for block in msg.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    c = block.get("content")
                    if isinstance(c, list):
                        tool_chars += sum(len(x.get("text", "")) for x in c if isinstance(x, dict))
                    elif isinstance(c, str):
                        tool_chars += len(c)
    billable = (
        usage["input_tokens"]
        + usage["cache_creation_input_tokens"] * 1.25
        + usage["cache_read_input_tokens"] * 0.1
    )
    return {
        "turns": len(sizes),
        "total_input_processed": sum(sizes),
        "billable_input_equiv": round(billable),
        "first_turn_context": sizes[0] if sizes else 0,
        "last_turn_context": sizes[-1] if sizes else 0,
        "work_context": (sizes[-1] - sizes[0]) if sizes else 0,
        "tool_calls": sum(tools.values()),
        "tools": dict(tools),
        "tool_output_tokens_est": tool_chars // 4,
        "started": stamps[0] if stamps else None,
        "finished": stamps[-1] if stamps else None,
    }


if __name__ == "__main__":
    print(json.dumps({p: summarise(p) for p in sys.argv[1:]}, indent=1))
```

## Results template

Fill in one row per run, then average.

| Run | Agent | Turns | Tool calls | Total input processed | Billable input | Work context | Tool output | Time | Correct (/12) | Tests found |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | without | | | | | | | | | |
| 1 | with | | | | | | | | | |
| 2 | without | | | | | | | | | |
| 2 | with | | | | | | | | | |
| 3 | without | | | | | | | | | |
| 3 | with | | | | | | | | | |
| **Avg** | without | | | | | | | | | |
| **Avg** | with | | | | | | | | | |

## Pilot run (4 tasks, 2026-10-03)

One run each, on tasks 7, 6, 5 and 8 in that order, with the same model for both agents.

| Metric | Without PRISM | With PRISM | Change |
|---|---:|---:|---:|
| Context at the first turn (fixed overhead) | 78,305 | 78,652 | same |
| Context at the end (the UI number) | 124,323 | 106,453 | −14% |
| Context added by the work | 46,018 | 27,801 | −40% |
| Model turns | 27 | 9 | −67% |
| Tool calls | 29 (14 Grep, 13 Read, 1 Glob) | 12 (7 Bash running prism, 4 Read) | −59% |
| Total input processed | 2,874,442 | 865,172 | −70% |
| Billable input (approx.) | ≈ 430,000 | ≈ 209,000 | ≈ −51% |
| Tool output read | ≈ 19,700 | ≈ 11,000 | −44% |
| Time | 120 s | 83 s | −31% |

**Quality** was about the same:
- **Task 7:** both agents named `parseApiError`.
- **Task 5:** both chose `update_status` and also named `_sync_standard_tracking`.
- **Task 8:** both chose `get_window` and named `build_kpis`.
- **Task 6:** both chose a backend timezone cause, but different functions.
- **Extra detail:** the agent without PRISM caught one more related problem, in `AuthContext.login`.

**Weakness found:** PRISM did not map Django `tests.py` tests to the code they cover, so the PRISM
agent reported "none found" where the other agent found `OrderTrackingTests`.

**Caveat:** this is a single run of 4 tasks. The 12-task, 3-run benchmark above is what gives
reliable numbers. The fixed overhead dominates short runs, so the gap should widen with more tasks.

## Task file for the token harness

For the modelled benchmark, `python -m tests.benchmarks.tokens --repo <platforma> --tasks tasks.json`:

```json
[
  {"request": "email verification codes are rejected as expired even right after they are sent", "target": "backend.core.models.EmailCode.verify"},
  {"request": "components crash because the logged in user is undefined outside the auth provider", "target": "frontend.zesty_app.src.contexts.AuthContext.useAuth"},
  {"request": "OLAP cube query returns wrong totals when filtering by a dimension", "target": "backend.warehouse.olap.queries.resolve"},
  {"request": "restaurant detail endpoint returns 404 when the restaurant is looked up by slug", "target": "backend.zesty.views.RestaurantViewSet.get_object"},
  {"request": "order tracking status does not advance after the restaurant accepts the order", "target": "backend.zesty.views.OrderViewSet._sync_standard_tracking"},
  {"request": "dashboard revenue chart puts orders in the wrong day bucket near midnight", "target": "frontend.zesty_app.src.components.dashboard.theme.bucketByDay"},
  {"request": "login form shows [object Object] instead of the server error message", "target": "frontend.zesty_app.src.api.auth.parseApiError"},
  {"request": "KPI percentage change compares against the wrong previous period", "target": "backend.core.analytics.build_kpis"},
  {"request": "warehouse ETL creates duplicate dimension rows for slowly changing dimensions", "target": "backend.warehouse.etl.load._bulk_scd2_load"},
  {"request": "simulated payments succeed even when the payment should fail", "target": "backend.core.models.Payment.simulate_payment"},
  {"request": "API response cache keeps serving stale data after the TTL expires", "target": "frontend.zesty_app.src.utils.cache.APICache.set"},
  {"request": "after signing in users are redirected to the wrong page", "target": "frontend.zesty_app.src.utils.helpers.getPostAuthRedirectPath"}
]
```
