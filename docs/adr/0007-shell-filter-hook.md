# 0007: Keep shell filtering explicit

Date: 2026-10-11. Status: accepted (master plan T20, Branch B).

Claude Code 2.1.296 accepts `PreToolUse.updatedInput` without a permission
decision. A native echo experiment executed the rewritten marker. With an
explicit ask rule for the rewritten command, the host denied execution.

However, a third native experiment denied the original echo and allowed its
`prism filter` wrapper. The wrapper executed the denied original command. The
hook returned no `permissionDecision` in any experiment. The host checks the
updated input; an opaque wrapper changes which command its permission rules
recognize. The hook input does not carry the original resolved authorization.
Reimplementing all host permission rules would be unreliable.

Therefore PRISM installs no automatic Bash rewriting hook. Users explicitly run
long commands as `prism filter -- <cmd>` with their usual host permissions.
Generated instructions describe this pattern. Doctor reports measured savings
from saved output metadata, or says no measurements are available.

Evidence: native experiment
and wrapper boundary.
Raw JSONL sessions accompany these summaries. The first `--bare` attempt failed
before inference because that mode disables OAuth and hooks; it is excluded.
A read-only echo without an explicit ask rule was automatically allowed and was
not used as the negative permission control.

The [host hook documentation](https://code.claude.com/docs/en/hooks) documents
permission evaluation against the updated input. These tests used existing
Claude.ai authentication, removed API credentials, and never forced an allow
decision. No paid API run was authorized.
