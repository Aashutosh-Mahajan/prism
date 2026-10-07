# Module `prism.navigator.text`

<!-- prism:generated:facts -->
- Files: prism/navigator/text.py
- Docstring: Tokenization and BM25 scoring for `prism search`.
- Public API (by importance):
  - `stem(word: str) -> str` — Light, deterministic suffix stripping so "recording" meets `record` and "enabled" (prism/navigator/text.py:139)
  - `tokenize(text: str) -> list[str]` — Stemmed words, lowercased, with snake_case and camelCase split. Whole identifiers are (prism/navigator/text.py:159)
  - `bm25(tf: float, df: int, n_docs: int, doc_len: float, avg_len: float) -> float` (prism/navigator/text.py:185)
  - `term_counts(fields: Iterable[tuple[str, int]]) -> Counter[str]` — Weighted bag of words: each (text, weight) field contributes its tokens `weight` times. (prism/navigator/text.py:176)
- Used by: `prism.navigator.cache_db`, `prism.navigator.graphify`, `prism.navigator.literals`, `prism.navigator.overview`, `prism.navigator.request`, `prism.navigator.source_index`, `prism.navigator.store`, `prism.navigator.synonyms`, `prism.navigator.task_pack`
- Tests: tests/unit/test_navigator.py
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:summary -->
