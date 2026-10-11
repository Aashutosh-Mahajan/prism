# Call resolution in schema 1.1

Each call edge has `confidence` and `resolution`. Confidence preserves the
existing high/medium/low ranking. Resolution records the evidence:

| Resolution | Meaning |
| --- | --- |
| `resolved` | Local scope, explicit import, a receiver type, or class inheritance identifies the target. |
| `name` | A unique method name supplies an inferred target without receiver evidence. |
| `ambiguous` | Multiple candidates prevent choosing a target. |

Ambiguous calls are serialized under `ambiguous_calls`, with caller, source
expression, line and sorted candidate IDs. They do not become invented edges,
confirmed callers, or PageRank links. The edge schema also accepts `ambiguous`
for compatible producers; navigator caller queries exclude such edges.

Task packets mark inferred name matches with `~`, show at most three of them,
and include resolution in structured caller rows. A typed or inherited call
can have medium confidence while still being resolved. Dynamic dispatch and
framework conventions can remain unresolved; these fields are static evidence,
not a claim of language-server accuracy.

Run `prism migrate` in an enabled repository to rebuild a schema 1.0 index as
1.1. The migration preserves decisions and narrative notes. It refuses to
write when PRISM is disabled or paused. Old committed artifacts can still be
read: the disposable query cache uses the former confidence rule as a fallback
until the owner migrates or updates the index.
