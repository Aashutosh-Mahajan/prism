# T16b persisted call resolution

Adopt schema 1.1 with explicit `resolved` and `name` edge evidence and separate
`ambiguous_calls` candidate records. Ambiguity does not create false targets or
alter graph ranks. Query-cache format 7 carries resolution into caller rows;
legacy artifacts retain a confidence-derived fallback. Typed and inherited
medium-confidence calls can now remain resolved rather than consume the
three-inferred-caller allowance.

The 1.0 migration performs a full rebuild and preserves owner notes. It refuses
disabled and paused repositories. The new version is published with successful
artifact generation, rather than before a rebuild that might fail.

Focused graph, migration, schema, golden and incremental-equivalence checks ran.
The full optional-grammar suite's first pass found one old mock lacking the new
resolution field. Updating that contract passed the focused checks; the full
confirmation suite then passed. Ruff and strict package mypy passed. Golden
changes were limited to schema versions and the new call-resolution fields.

The remaining Phase 3 replay will check the owner-approved frozen recall gate
after the final retrieval-affecting changes. No native cost improvement is
inferred from this offline result.
