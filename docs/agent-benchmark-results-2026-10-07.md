# Agent benchmark: edit tasks with and without PRISM, 2026-10-07

Fifteen fresh Claude agents (5 change requests × 3 setups) each made one edit in an isolated
copy of a real full-stack project (Django + React/TypeScript, 384 files, about 60,000 lines).
Every edit was scored by executable checks, and every session was measured from the agent's own
transcript. This is the first benchmark of PRISM that asks an agent to *change code* and checks
the result, in a fresh session per task (the case PRISM is built for: no re-orienting in each
new session).

## Setups

| Setup | What the agent has |
|---|---|
| **without** | Its normal tools (Glob, Grep, Read, Edit, read-only shell). No `prism`. |
| **tool** | PRISM installed: the compact session brief and the short instruction block in context, `prism task` available. The agent decides when to call it. |
| **hook** | As **tool**, plus what the `UserPromptSubmit` hook adds to the request: the output of `prism hook user-prompt` for that request, produced by the real hook code. |

The brief, the instruction block and the hook output are exactly what an installed PRISM puts
in context; the harness pastes them into the prompt because the agents run as subagents without
the host's hooks. Prompts differ between setups only in those blocks. All agents used the same
model and the same task text.

## Result

All **45 edits passed every check** in all three setups (27/27 checks each).
Averages over the five tasks:

| Metric | without | tool | hook |
|---|---:|---:|---:|
| Model turns | 4.6 | 3.8 (-17%) | 3.2 (-30%) |
| Tool calls | 6.6 | 4.6 (-30%) | 3.4 (-48%) |
| Total input processed (tokens) | 408,793 | 320,268 (-22%) | 269,532 (-34%) |
| Billable-equivalent input | 149,228 | 132,469 (-11%) | 126,860 (-15%) |
| Context added by the work | 17,081 | 9,746 (-43%) | 7,888 (-54%) |
| Tool output read (est. tokens) | 4,582 | 1,528 (-67%) | 493 (-89%) |
| Wall time (s) | 25.4 | 24.9 (-2%) | 18.7 (-26%) |
| Edit checks passed | 27/27 | 27/27 | 27/27 |

Per task, billable-equivalent input / model turns:

| Task | without | tool | hook |
|---|---:|---:|---:|
| 1. A lifetime constant that is also written into UI copy | 187,688 / 6 | 136,209 / 4 (-27%) | 135,698 / 4 (-28%) |
| 2. Add a field to every KPI an analytics helper builds | 142,208 / 4 | 136,483 / 4 (-4%) | 125,784 / 3 (-12%) |
| 3. Show the server's error message instead of a generic one | 155,509 / 6 | 133,622 / 4 (-14%) | 124,795 / 3 (-20%) |
| 4. Make a simulated payment fail for non-positive amounts | 128,400 / 3 | 132,334 / 4 (+3%) | 132,851 / 4 (+3%) |
| 5. Rename a constant everywhere it is used | 132,336 / 4 | 123,698 / 3 (-7%) | 115,172 / 2 (-13%) |

"Billable-equivalent" is uncached input + 1.25 × cache writes + 0.1 × cache reads, the plan's
proxy for what prompt caching makes you pay. It is not an invoice. "Total input processed" sums
the whole context sent on every turn, which is what a longer session re-sends.

## Reading the numbers

- **The hook setup saves the most because it removes turns, not just tokens.** The answer is in
  the prompt, so the agent edits at once: 3.2 turns against 4.6, and the
  tool output it reads falls by 89% (greps and file reads it no longer makes). Each avoided turn
  avoids re-sending the whole context.
- **The fixed cost of PRISM is small.** The context at the first turn is 77,130 tokens without PRISM,
  77,591 with the tool setup (+461) and 78,985 with the hook (+1,855, which includes the
  request's answer). About 77,130 tokens of that is this environment's system prompt and tools,
  paid on every turn in every setup; that fixed overhead is why billable input moves less than
  total input.
- **Where PRISM did not help: task 4**, a one-method change to an easily greppable name. The
  agent without PRISM needed a grep, a read and an edit (3 turns); with PRISM it took 4. For an
  edit this small PRISM has nothing to save, and the answer it adds is a few hundred extra tokens.
  This is the regime where plain search is hard to beat.
- **Where it helped most:** tasks whose locations are scattered (1: a constant plus UI copy in
  two other files, 5: every use of a constant) and tasks needing callers (2, 3). In task 1 the
  agent without PRISM made 6 greps; the PRISM setups made none after the answer.

## Compared with the earlier benchmark of the same project

The first agent benchmark of the edit tasks (before the changes this release makes) compared a
PRISM that returned file-level excerpts with an agent's normal tools on tasks 1-3:

| Tasks 1-3, total input processed | Earlier PRISM | This release, tool | This release, hook |
|---|---:|---:|---:|
| Change vs without PRISM | -6.1% | -30% | -42% |

The earlier run also took 29% longer than the baseline; here **tool** is -2% and **hook** is -26%. What changed: `prism task` now lists every
exact occurrence of the request's strings, names and quantities (so the agent has no reason to
grep for them again), returns whole small functions instead of file headers, lists call sites
with their calling line, keeps its answers small, answers from the working tree, and the
prompt hook delivers the answer with the request.

## Caveats

- One run per cell, five tasks, one repository: these are measurements, not a guarantee.
  Differences of a few percent between setups are within run-to-run noise.
- Agents ran as subagents, so the hooks' output was supplied by the harness rather than by a
  host that runs them. The hook text is the real output of `prism hook user-prompt`; the host
  behaviors this does not exercise are each agent's own hook plumbing.
- The tasks have exact, checkable outcomes. They are small and specific, which is where an
  index helps the least; larger repositories and vaguer requests are expected to favor PRISM
  more (see [benchmarks](benchmarks.md) for the scaling argument), but are not measured here.
- Every agent shares a large fixed system prompt, so savings in *billable* input are bounded
  well below savings in the tokens the agent actually reads.

## Reproducing

```bash
python -m tests.benchmarks.edit_bench prepare --repo <repo> --tasks <tasks.json> --out <dir>
# run one fresh agent per prompt in <dir>/prompts, inside <dir>/<task>/<arm>
python -m tests.benchmarks.edit_bench verify  --out <dir>
python -m tests.benchmarks.edit_bench measure --out <dir> --transcripts <transcripts> --map map.json
python -m tests.benchmarks.edit_bench report  --out <dir>
```

`tests/benchmarks/tasks/webapp_edits.json` holds an equivalent task set for the bundled web-app
fixture. `python -m tests.benchmarks.retrieval_eval` scores retrieval alone (no agent) on labeled
queries in seconds.
