# Module `prism.navigator.semantic`

<!-- prism:generated:facts -->
- Files: prism/navigator/semantic.py
- Docstring: Optional local semantic search (`pip install prism-ctx[semantic]`).
- Public API (by importance):
  - `class SentenceTransformerEmbedder` (prism/navigator/semantic.py:33)
  - `get_embedder(model: str) -> Embedder` (prism/navigator/semantic.py:104)
  - `hybrid_search(store: IndexStore, query: str, limit: int, embedder: Embedder) -> list[SearchHit]` (prism/navigator/semantic.py:80)
  - `semantic_model(root: Path) -> str` (prism/navigator/semantic.py:110)
  - `class Embedder(Protocol)` (prism/navigator/semantic.py:27)
- Depends on: `prism`, `prism.core`, `prism.navigator.cache_db`, `prism.navigator.store`
- Used by: `prism.navigator.api`
- External: sentence_transformers
- Tests: tests/integration/test_phase5.py
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:summary -->
