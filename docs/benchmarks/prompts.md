# Reusable prompts

Render only the common prompt, one arm block, and the task's `agent_visible` fields. Never expose evaluator-only fields. These are templates for future runs, not instructions to the current authoring agent.

## Common prompt

You are working in the assigned isolated repository. Complete the following task and run the relevant available checks. Investigate as much as needed to make a correct change. Follow applicable project conventions. Do not weaken tests, hardcode expected outputs or modify benchmark machinery. If requirements are genuinely ambiguous, explain the specific missing information; do not invent it. Finish with the change summary, checks run and any unresolved issue.

Task: {{request}}
Acceptance requirements: {{acceptance_requirements}}
Available verification commands: {{verification_commands}}
Constraints: {{constraints}}

## Baseline arm block

Use the ordinary tools available in this environment to locate and edit the relevant code. Targeted search and focused file reads are allowed. Prism is not available in this trial.

## CLI arm block

Use `prism task "<actual task request>"` once to obtain relevant code evidence. Use the supplied evidence directly. If it is partial, read the requested follow-up ranges; if it is weak, use targeted search. Ordinary investigation and verification tools remain available. Do not initialise or rebuild the environment manually; report setup failures.

## MCP arm block

Use the native `prism_task` tool once with the actual task request to obtain relevant code evidence. Use the supplied evidence directly. If it is partial, read the requested follow-up ranges; if it is weak, use targeted search. Ordinary investigation and verification tools remain available. Do not initialise or rebuild the environment manually; report setup failures.

## Native preflight replacement block

If Prism evidence is supplied with this task, use it directly without retrieving it again. Follow explicit missing-range guidance or use targeted discovery if evidence is insufficient. Complete the edit and verification normally.

The host must actually deliver the packet and record its trace. Do not add this block to a baseline run. Do not use the CLI/MCP retrieval-first block in a preflight run.

## Session extension

Send one task at a time after saving the previous task's usage and verification outcome. Keep the agent history and Prism session ID through the whole sequence. Start a fresh session for every new sequence/repetition/arm. Register how a failed earlier edit affects later tasks; default to continuing from the actual resulting state in all arms and score the complete sequence.

## Blind reviewer prompt

Evaluate this anonymised task result against the frozen acceptance requirements and supplied evaluator logs. Accept valid alternative implementations. Record each unmet requirement, prohibited shortcut and regression with evidence. Return binary verified success plus the frozen diagnostic rubric. Do not infer quality from token counts or tool usage. Escalate ambiguous oracle requirements for adjudication without seeing arm labels.
