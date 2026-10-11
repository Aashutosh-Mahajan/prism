# Trust and token fixes — 10 October 2026

Source: the local reliability matrix run on 9 October 2026 against a frozen copy of Prism, and the
first real Antigravity run on ArogyaTrack (12 sessions, about 32% fewer total tokens with the CLI,
18% with MCP). This note lists every defect fixed, how it was verified, and what is still open.

## Fixed, with the cause and the check

| # | Defect | Cause | Fix | Verified by |
|---|---|---|---|---|
| 1 | Source never delivered after a lost reply | Ranges were recorded as delivered when the packet was *built* (CLI, MCP, hooks) | Two-phase delivery: ranges stay pending until a *different* next request in the session proves the reply was read; an identical request is a retry and resends the source. `session.py` format v3 | reliability MCP-15c/15d (3/3 failing before, 0/3 after); `test_identical_retry_resends_source…`, `test_unread_reply_is_never_treated_as_delivered…` |
| 2 | "Exhaustive" literal lists missed Cyrillic, CJK, Hebrew, accented and decomposed text; identifiers truncated at the first non-ASCII letter | ASCII-only tokenizer and regexes | Unicode-aware tokenizer, regexes and postings (`source-v3.sqlite`); canonical (NFC) matching; the user's own spelling is echoed back | IDX-06, `test_non_ascii_*`, `test_decomposed_text_…` |
| 3 | A name was reported "new / does not exist" when it existed inside a longer word, or only in a file skipped for size | Absence was decided from whole-word postings alone | Absence is now proved by scanning indexed text, then the size-skipped files; otherwise the result is marked limited | IDX-07, IDX-08, `test_name_inside_a_longer_word…`, `test_a_name_only_in_a_size_skipped_file…` |
| 4 | Latin-1 and lone-CR Python files had wrong text or line numbers; a stray bad byte hid a file's symbols | One lossy UTF-8 decode and `\n`-only splitting | One shared decoder (`core/textio.py`: BOM, PEP 263 coding, tolerant fallback); Python line rule matches `ast` | IDX-07, `test_latin1_and_lone_cr…`, `test_file_with_stray_invalid_utf8…` |
| 5 | A request like "change the age from 23 to 25" listed no sites for the old value, so agents grepped | Numbers were only searched next to a unit word | The old value is searched everywhere it is stated, in files that also talk about the topic (including sibling lines such as `year - 23`), shown as an exhaustive list | ArogyaTrack packet: low confidence / 1,858 tokens / frontend site missing → high confidence / 1,587 tokens / all 12 sites; `test_changed_number_…` |
| 6 | Incremental updates differed from a fresh scan | Approximate (kept) PageRank scores on every small update | Exact PageRank below 5,000 symbols; lazy only above | FRS-10 |
| 7 | Syntax errors in JS/TS/Go/Java were not reported; Java `apply(x)` and `this.apply(x)` calls were not linked | Tree-sitter parsers ignored `has_error`; resolver knew only Python `self` | `parse_error` is recorded and shown by `prism doctor`; unqualified and `this.` calls resolve to the enclosing class | IDX-02, IDX-03 |
| 8 | A cached answer built by an older engine could be served after an upgrade | Packet cache key ignored the code | Cache key includes an engine fingerprint | found while verifying #3 |
| 9 | Reading a repo the user never enabled wrote files into it; a running MCP server kept serving after `prism disable` | Caches lived inside the repo; consent was read once at start | Caches for an unenabled repo go to the user's own config dir; MCP re-checks consent on every call | CLI-10, MCP-14, `test_a_repo_the_user_never_enabled…`, `test_mcp_stops_serving…` |
| 10 | MCP `format=json` sent the packet twice (x2.83 bytes) | `content` and `structuredContent` both carried it | One copy, in text content | MCP-05b |
| 11 | CLI exit codes: usage errors exited 2 (reserved for "index missing"); bad `--root` accepted; "not initialized" gave no next step | Click defaults | Usage errors exit 1; `--root` must be a directory; the message says how the user enables PRISM and that agents must not | CLI-02b, 03b, 06b |

## Added to make agents stop searching

- **Edit-ready verdict.** When literal lists are complete the `Next:` line says "Edit-ready: N listed sites in M files are exhaustive; edit them now, no repo-wide search."
- **Verify mode.** `prism task "<same request>" --mode verify` (MCP: `mode="verify"`) re-reads the working tree and lists only the sites that still match the old value, with no source blocks. It replaces the repo-wide grep an agent otherwise runs after editing.
- **No bare imports as "missing source".** One-line import ranges are no longer offered as ranges to read.
- **Instructions.** The `CLAUDE.md` block, the skill and the MCP instructions now state the stop rule and the verify step.

## Checks that were wrong, not Prism

Four reliability checks were corrected after investigation: the oracle read latin-1 files as lossy UTF-8; it split lone-CR files on `\n`; FRS-02 expected one occurrence too many; FRS-13 flagged the `\r\n` that Windows text-mode stdout adds, and FRS-10 compared `AGENTS.md` titles that come from the folder name.

## Status

Unit and integration tests, ruff and mypy pass. Reliability: indexing and freshness 23/23, CLI 18/18, MCP 25/25, repeated-session 2/2 (area 1 of the matrix; retrieval, budgeting, cache, parity, hooks, isolation, robustness and optional features are still to run).

## Not done

Semantic retrieval changes, the narrative layer, test selection, learned ranking feedback, deeper Dart/Kotlin parsing, and a prompt-hook preflight experiment were not part of this change. Token effect of these fixes on real agents is reported separately in the benchmark results.
