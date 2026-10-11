# Phase 2 context and shell changes

Transport defaults remain unchanged until T41 has paired correctness and cost
evidence. No automatic Bash rewrite hook is installed. ADR 0007 records the
native permission tests and the explicit filtering fallback.

Saved shell output supports bounded literal grep, nearby lines, tail, and complete
UTF-8 retrieval. A 3,000-line fixture and a CRLF byte test pass. Saving failure
prints all output and preserves a failing exit code. Doctor reports savings
from actual saved metadata, including the retrieval footer.

Instructions now share one module. The entry-point skill links its advanced
reference; installation plans enumerate both files and uninstall restores owner
content. Explicit workflow skills disable model invocation. Native Claude Code
2.1.296 `/context` measures PRISM's default skill listing at approximately 50
tokens. The host's built-in skills make the total listing 2.2k; PRISM does not
control those built-ins. The Codex skill validator accepts prism-context; its
frontmatter schema does not support Claude's workflow-only flag. Installation
and skill contract checks validate those workflows separately.

Standing text is measured as hook + MCP + generated project block, against the
pre-change forms (177 CLI words, 203 MCP words). The final counts are recorded
in phase2-instructions-2026-10-11.json; both meet a 30% reduction.

An actual native `/compact` emitted `SessionStart.source=compact`. PRISM cleared
the source ranges and reinjected the current handoff note. Ordinary startup
still excludes the current session, while compaction restores its notes.
The compaction directory contains raw host events, hook input, orientation
output and summary. Another session's source memory is preserved in the fixture.

Edit packets warn about slow suites only for an explicit owner flag or a recorded
full pytest run over 120 seconds. Selected test runs cannot overwrite that
measurement; an owner flag without a measurement never invents a duration.

Display sanitation removes hidden controls and multiline Markdown HTML comments
while preserving source line coordinates. Raw source remains available for
checked edits. Instruction documents require an explicit request. A fixed
quoted-data line and dynamically sized source fences keep embedded backticks
inside the excerpt. The replay parser supports those fences. Doctor flags hidden
controls in indexed source.

`prism impact --changed` combines staged and unstaged hunks without refreshing
the index. It reports indexed symbols, one-hop callers and tests, risk reasons,
omissions and conservative old/new coordinate mapping. The fixture verifies
source/index bytes remain unchanged, budget limits, and warm lookup under 0.5 s.
New/deleted or unindexed files are disclosed as unmapped.

Obsidian export has a sorted index, cluster membership notes, shared frontmatter
and human-only guidance. Two exports are byte-identical and fixture wikilinks
resolve. User-owned note collisions are refused. Module placeholders are hidden
from agent-facing module and brief responses; `refresh --top N` prepares ranked
module sections for the host agent, retaining the existing commit validator.
Doctor reports their fill ratio.

This is implementation evidence. The Phase 2 replay and paired transport decision
are separate acceptance requirements; no live correctness benefit is claimed.
