# Module `prism.navigator.knowledge`

<!-- prism:generated:facts -->
- Files: prism/navigator/knowledge.py
- Docstring: A bounded inspection of the persistent project knowledge, not a source dump.
- Public API (by importance):
  - `knowledge(store: IndexStore, budget: int = 600) -> dict[str, Any]` (prism/navigator/knowledge.py:29)
  - `render_knowledge(packet: dict[str, Any]) -> str` (prism/navigator/knowledge.py:14)
- Depends on: `prism.core`, `prism.navigator.store`
- Used by: `prism`, `prism.navigator.api`
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
Produces a bounded inventory of indexed files, symbols, calls, imports, languages and important modules. It describes local persistent knowledge without sending the whole source tree to the model.
<!-- /prism:narrative:summary -->
