# ADR 0006: bounded hook output

Status: accepted, 11 October 2026.

Claude Code's hook context is limited to 10,000 characters. PRISM reserves
headroom and bounds injected context to 9,500 characters by lowering retrieval's
budget, rather than cutting a source line or dropping its recovery footer.
The setting still accepts 128–8,000; doctor warns when its character estimate
exceeds the delivery cap. The format adapter rejects oversized context as a
last defense. JSON envelopes carry additionalContext; text hosts use stdout.

PRISM does not depend on updatedToolOutput. It does not approve commands or
replace built-in tool results. Original command output remains recoverable.
