# Master improvement plan execution

Owner requested the full plan on 11 October 2026. DevRelay MCP was removed first.
Existing uncommitted delegation/retrieval work is preserved and not included in
task commits. Codex gpt-6-luna using the existing subscription is authorized for
live measurements; paid API execution is not authorized. The owner explicitly
deferred Anthropic token-count measurement; token_scale remains 1.0 by default.

| Task | Status | Evidence / outstanding work |
| --- | --- | --- |
| T00 | committed | 5054b58; 40 parent replays in 298 s; fixed 10-request audit; 13 tests |
| T01 | committed | e61ef6e; token classes, pricing branches, pass@1/pass^k, dollars and frozen-cache costs; original 60-session pass counts unchanged |
| T02 | implemented; measurement deferred by owner | optional deterministic scale, 50-sample manual harness; no credential configured; default 1.0 |
| T03 | committed | 2b43f51; root 142 lines / 1,497 estimated tokens; verbatim linked specifications and short nested rules |
| T04 | committed | c59bc78; 9,500-character cap through smaller retrieval budget; doctor warning and ADR 0006 |
| T05 | committed | 22c18c2 + 5755671; specific patch refusal codes; six safety branches tested plus cache failure |
| T10 | committed | da42c72; 80-site checked compact patch; 450-site refusal; replay recall and precision unchanged |
| T11–T15, T16a | accepted; 4b006fe | final replay precision 20.0339%, file recall 14.7541% (within 2 points), mean 624.725; format saving 13.3349%; adaptive audit 681.9; parity and offline suite pass |
| T16b | committed; b855cfc | schema 1.1 resolution provenance and ambiguity; migration preservation; full offline suite, Ruff and mypy pass |
| T20 | implemented; Branch B | native permission experiment and ADR 0007; explicit filtering only |
| T21 | implemented | saved-output round trip, CRLF, query and fallback checks |
| T22 | pending paired data | transport defaults unchanged |
| T23 | implemented; native listing measured | PRISM ~50 tokens; total host listing 2.2k includes built-ins |
| T24 | implemented | shared rules; standing word count reduced >30% |
| T25 | implemented; native compact verified | actual source=compact hook; seen ranges cleared; other session preserved |
| T26 | implemented | recorded full pytest duration or explicit flag; edit packets only |
| T27 | implemented | hidden controls and multiline Markdown comments removed; instruction docs require named request |
| T28 | implemented | staged/unstaged symbols, callers/tests, budgeted JSON, warm fixture <0.5 s |
| T29 | implemented | deterministic linked index/cluster notes and common frontmatter |
| T30 | implemented | placeholders hidden; ranked --top preparation; validator commits; doctor fill ratio |
| T40 | committed; ef964a4 | offline file/block/line scorer and owner-approved regression gate |
| T41 | pilot running | native hooks verified; frozen ten-task paired/interleaved pilot; full campaign still required |
| T42 | committed; bbc1f5f | sequential pinned local comparison; retain optional MiniLM; raw scores and checker audit |
| T43 | pending | post-edit dependent hint experiment must satisfy paired edit/cost acceptance |
| T44 | committed; ae49472 | conservative language-server doctor guidance |
| T45 | language commits complete | optional AST grammars and incremental equivalence; separate PR publication pending |
| T46 | in progress | current launcher and daemon measurements; 200 ms p95 not yet met |
| T47 | committed; ae49472 | 500-log cleanup verification; bounded count/size/age |
| T48 | implemented; exclusion verified | 22 historical documents archived; supplied audit bytes preserved; no broken live links |

Validation environment: sandboxed Windows asyncio stalled creating its loopback
socket pair. Tests run with local loopback access but retain the external-network
blocker. Temporary fixtures must be outside this Git repository; otherwise fixture
copies inherit its Git/index state. The three failures from workspace-contained
temporary files passed individually with corrected isolation.

Phase 0 automated validation passes: full offline suite, Ruff and strict package
mypy. T02 API measurement is deferred by owner approval. Claude Code 2.1.296 /context now confirms project CLAUDE.md at 2.3k tokens
and total memory at 2.4k, with MCP disabled and no session persistence. No startup
length warning was emitted. T02 commits: 33257ea + 08d7c4c. Phase 1 is accepted; Phase 2 is in progress.
Do not interpret implementation as
acceptance where live, manual or regression measurements are still outstanding.

Owner changed the Phase 1 precision gate to improvement over the pinned measured
baseline (18.86285%), preserving the original recall and size requirements.
The 55% absolute target is no longer the acceptance gate. First selector replay:
11.6889%; matched-excerpt replay: 15.9708%; two-candidate edit replay: 18.0650%.
None passes the precision gate. Final compact-format replay passes: 20.0339% precision, 14.7541% recall, mean
624.725 estimated tokens.

T14 smoke pilot: gpt-6-luna, Codex CLI, ChatGPT login, API credentials removed,
no paid API authorization. One isolated small fixture, segment-only source line
numbering, successful edit and three independent assertions; 33.86 seconds.
This is a formatting check, not a T41 benchmark arm. Raw pilot events are under
output/benchmarks/format-pilot; native reported input 100,983, cached input 85,760,
output 536, reasoning output 82. These are subscription usage, not a dollar bill.

T21 is implemented locally with thirteen passing output-filter tests, but is
not marked accepted as a phase milestone while the Phase 1 gate is outstanding.

Final-format audit: 37,803 legacy characters vs 32,762 compact characters,
13.3349% savings for identical parsed source blocks and delivered lines.
Latest adaptive audit: 681.9 estimated tokens, zero test-source characters and
zero test callers on non-test requests. Final replay and full offline suite pass.
The sufficient rate is 2/10 for both fixed and adaptive budgets after selection
changes; T00 was 3/10. The ladder itself did not reduce this rate.

Caller oracle: all six production call sites for build_task/render_task in the
pinned repository are delivered, plus the independent fixture source oracle.
A final focused test verifies the inferred-caller limit is three across the
whole packet, with resolved callers retained for both targets. Earlier replay
packets had at most one delivered inferred caller; audit packets had none.
All refusal codes now have coverage, including generic_name and budget_exceeded.

T20: native updated-input experiment and permission boundary recorded in ADR 0007; Branch B selected, no automatic rewriting hook. T21 saved queries and T23 supporting-resource install/uninstall checks pass. T24 shared instruction rules and T25 compaction reset are implemented; further live checks remain pending. T22 defaults remain unchanged pending paired data.

Phase 2 focused integration batch: 92 checks pass. First full offline run had 14 failures tied to intentionally changed instruction/skill wording; updated contracts and all 79 affected prompt/transport/skill/parity checks pass. Full confirmation passes; the late current-note compaction addition also passes all 30 gate/work-log checks. Ruff and strict package mypy pass. T40 offline scorer added with exact file and line metrics, overlap block metrics and explicit observed usage only; unknown transcript usage is not scored as zero.

T40: pure scorer and its owner-approved regression gate pass against the frozen T00 and accepted Phase 1 reports. Reports include engine digest/dirty provenance; actual transcript-use and provider-cost evidence is unavailable in these offline packets. Phase 2 replay remains to run after the implementation commit.

Phase 2 implementation committed as 6d3c603. T40 committed as ef964a4. Phase 2 parent replay: precision 20.0339448%, file recall 14.7540984%, mean 628.95 estimated tokens; file/block/line metrics match the accepted Phase 1 scores. T22 remains pending native paired transport data. T41 pilot preparation is frozen; native hook preflight is running.

T44 and T47 committed as ae49472: conservative language-server doctor guidance,
bounded saved-output cleanup, cache-size reporting, 500-log limit verification.
Dart (dac89bf), Kotlin (7fe04a8) and Swift (ab8e3c2) optional AST grammars each
have their own language-specific commit and pass fixture/caller checks plus
two-edit full artifact equivalence. Language-specific PR publication remains.

T16b schema 1.1 is implemented. Full offline confirmation with all three optional
grammars passes, as do Ruff and strict mypy. Migration preservation, consent
refusal and failed-rebuild publication checks pass. The former inference-cap
mock was updated to provide explicit resolution evidence.

T41 native diagnostics are preserved and excluded from the pilot. Project trust
needed persisted configuration. A dedicated local Codex state directory fixed
the global Windows sandbox helper lock, using existing ChatGPT authentication
with no API fallback. Native hook delivery remains under investigation; no
hook-arm improvement is claimed. T42 has pinned local weights and a fixed
1,922-document historical corpus, 40 replay requests and nine real code-twin
queries. Initial retrieval scores are recorded; final timing verification and
recommendation remain.

T42 controlled sequential evidence is committed. MiniLM versus CodeRank file
recall@5: 14/61 versus 18/61; recall@10: both 19/61. Code-twin recall@5:
12/16 versus 11/16; @10: both 16/16. CPU and GPU timing configurations differ.
Native Transformers loads CodeRank with remote-code trust disabled. Retain the
current default; Jina was excluded before weight download for its license.

T48 moves 22 dated historical records under docs/archive, excludes that tree
and immutable benchmark JSON/JSONL via .prismignore, and repairs live Markdown
links. The supplied superseded audit's SHA256 is unchanged:
d7fe7d0370910bceaeba76cba55bff4ae39a09960c42be408281ee9912ecc172.
Source and text retrieval exclusion integration checks pass; live link audit
finds zero broken links. The active master plan remains at its original path.
