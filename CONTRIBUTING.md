# Contributing to PRISM

Thanks for helping make PRISM better. This guide covers the development setup, the checks every
change must pass, and the rules that keep PRISM trustworthy.

- [Ground rules](#ground-rules)
- [Development setup](#development-setup)
- [Project layout](#project-layout)
- [Making a change](#making-a-change)
- [Checks](#checks)
- [Testing guide](#testing-guide)
- [Working on the viewer](#working-on-the-viewer)
- [Common tasks](#common-tasks)
- [Commits and pull requests](#commits-and-pull-requests)
- [Reporting bugs and requesting features](#reporting-bugs-and-requesting-features)

## Ground rules

[CLAUDE.md](CLAUDE.md) is the product specification. When your instinct and the spec disagree,
the spec wins; when the spec looks wrong, open an issue instead of silently diverging.

Every change is checked against these non-negotiable principles:

| Principle | What it means for your change |
|---|---|
| Local and offline | No network calls from PRISM's core. The test suite blocks sockets; any network call fails the build. |
| No API keys | PRISM never calls an LLM. Reasoning is delegated to the user's agent through skills and tools. |
| Deterministic index | Same code in, same `.aicontext/` bytes out: sorted keys, stable ordering, timestamps only in `manifest.json`. |
| Incremental | A one-file change re-parses one file. Don't add work to `update` that belongs in a full scan. |
| Retrieval over dumping | Every agent-facing output has a token budget. Never make the agent read more by default. |
| Plain artifacts | JSON and Markdown with documented schemas. Schema changes need a version bump and a migration. |
| Zero-config | `prism init && prism scan` must work in any supported repo without configuration. |
| Agent-agnostic core | The core knows nothing about specific agents. Integrations live in `prism/integrations/` and only install files. |
| Safe by default | PRISM never modifies user source code. |
| Opt-in | Nothing runs in a repository until the user enables it there, per user. |

Before adding anything, ask the questions in [CLAUDE.md §20](CLAUDE.md#20-before-you-add-anything-ask).

## Development setup

Requirements: Python 3.10+ and Git. Node 24 only if you work on the graph viewer frontend.

```bash
git clone https://github.com/Aashutosh-Mahajan/prism
cd prism
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"            # add ,treesitter to work on JS/TS/Go/Java parsing
prism --version
```

> **Don't run `prism init` or `prism scan` against a repository you did not choose to index.**
> For experiments, copy a repository into a temporary directory and point `PRISM_CONFIG_HOME`
> at a scratch folder so your real consent registry is untouched:
>
> ```bash
> export PRISM_CONFIG_HOME=/tmp/prism-cfg
> cp -r path/to/some/repo /tmp/playground && cd /tmp/playground
> prism init --yes --no-hooks --no-mcp && prism scan
> ```

## Project layout

```text
prism/                 Python package
├── cli.py             Typer CLI (thin wrappers over library functions)
├── lifecycle.py       init / scan / update orchestration
├── pipeline.py        the indexing pipeline, stage by stage
├── discovery/         file walking, ignore rules, language detection
├── parsing/           Python ast parser, optional tree-sitter parsers, smells
├── graph/             symbol table, import and call graphs, PageRank, communities
├── extractors/        routes, models, config keys, entry points, tests map, toolchain …
├── health/            complexity, git intelligence, coverage, risk
├── drift/             structural diff and drift scoring
├── incremental/       parse cache for incremental updates
├── writers/           the only code that writes .aicontext/ (plus exports)
├── navigator/         search, locate, context packs, impact, SQLite query cache
├── narrator/          refresh prepare / commit for AGENTS.md
├── audit/             audit plan, finding store, reports
├── consent/           per-user enable registry
├── hooks/             session-start and post-edit hook runners
├── integrations/      Claude Code, Cursor, Codex/generic, git hooks (installers only)
├── mcp/               MCP server (tools map 1:1 to library functions)
├── viewer/            stdlib HTTP + SSE server and graph API for `prism view`
├── viewer_dist/       prebuilt frontend bundle (generated, never edit by hand)
├── schemas/           JSON Schemas for every artifact
└── templates/         shipped skills and the AGENTS.md skeleton
viewer/                TypeScript + Vite + Sigma.js frontend source
tests/                 unit, integration, skills, golden files, fixtures, benchmarks
docs/                  user and developer documentation, ADRs
```

See [docs/architecture.md](docs/architecture.md) for how the pieces fit together.

## Making a change

1. **Open or find an issue** for anything bigger than a small fix, so the approach can be agreed first.
2. **Create a branch** from `main`: `git switch -c fix/short-description`.
3. **Write the test first** where practical, especially for bugs.
4. **Keep layers clean:**
   - Pipeline stages communicate through typed dataclasses and never import from a later stage.
   - Only `prism/writers/` writes into `.aicontext/`.
   - The CLI, the MCP server and the viewer API are thin wrappers over the same library function.
     Never implement logic twice.
   - New extractors implement `Extractor` and register through the registry; no pipeline edits.
5. **Run the checks** below.
6. **Update the docs** that describe the behaviour you changed, and add an entry under
   *Unreleased* in [CHANGELOG.md](CHANGELOG.md).

## Checks

Every pull request must pass the same checks CI runs (Linux, macOS and Windows; Python 3.10–3.14):

```bash
ruff check prism tests
ruff format --check prism tests
mypy                                   # strict mode on prism/
pytest                                 # sockets are blocked for the whole suite
```

If you touched the viewer frontend:

```bash
cd viewer
npm ci
npm test
npm run build                          # regenerates prism/viewer_dist; commit the result
```

CI fails if `prism/viewer_dist` differs from a fresh build, so always commit the rebuilt bundle
together with the source change.

## Testing guide

| Kind | Where | Notes |
|---|---|---|
| Unit | `tests/unit/` | One module per source module, synthetic inputs. |
| Integration | `tests/integration/` | Full pipeline on fixture repos, CLI, MCP, viewer API, installers, consent. |
| Golden files | `tests/golden/` | Byte-exact `.aicontext/` output for the tiny fixture. |
| Skill consistency | `tests/skills/` | Every `prism …` command, flag and field a shipped skill mentions must exist. |
| Fixtures | `tests/fixtures/repos/` | `tiny`, `small`, `polyglot`, and `seeded` (with deliberate bugs listed in `SEEDED_BUGS.json`). |
| Benchmarks | `tests/benchmarks/` | Latency (`run.py`) and token savings (`tokens.py`); not part of the default run. |
| Viewer | `viewer/tests/` | `node:test` over the compiled graph, encoding and data-source logic. |

Rules of thumb:

- **Golden files.** If you intentionally change artifact output, regenerate and review the diff:
  `PRISM_UPDATE_GOLDEN=1 pytest tests/integration/test_scan.py`.
- **Incremental equivalence** (`scan` from scratch ≡ `scan` + N×`update`) is the most important
  correctness property. Any change to parsing, graphs or writers must keep it green.
- **Budgets.** The brief stays ≤ 600 tokens and the default context pack ≤ 2,000 tokens
  (tokens are estimated as characters ÷ 4).
- **Consent.** Hooks and the MCP server must do nothing in a repo that isn't enabled for the user.
- **Windows.** Tests run on Windows in CI. Open text files with `encoding="utf-8"` explicitly and
  use `Path.as_posix()` for repository-relative paths.

## Working on the viewer

```bash
cd viewer
npm ci
npm run typecheck  # tsc --noEmit
npm test           # compiles to .test-build/ and runs node:test
npm run build      # writes ../prism/viewer_dist
```

The development loop is: run `prism view --no-open` in a scratch repository (it serves
`prism/viewer_dist` straight from your editable install), then `npm run build` and reload the
browser after each change.

The viewer must work with the network unplugged: vendor every script, style and font into the
bundle (no CDNs). Keep it keyboard-accessible: every action reachable without a mouse, visible
focus, ARIA roles on custom widgets, and respect `prefers-reduced-motion`. See
[docs/viewer.md](docs/viewer.md) and [ADR 0002](docs/adr/0002-viewer-rendering-stack.md).

## Common tasks

**Add an extractor.** Create `prism/extractors/<name>.py` implementing `Extractor`, register it,
add its output to a writer and a JSON Schema in `prism/schemas/`, and add unit tests plus a
golden-file update.

**Add a CLI command.** Implement the logic in the library layer, add a thin command in
`prism/cli.py`, and, if agents should use it, a matching MCP tool in `prism/mcp/server.py`.
Update `docs/cli.md` and any skill that should mention it (the skill consistency test will
check the reference).

**Change a schema.** Bump the schema version, add a migration for `prism migrate`, update the
JSON Schema, the skills that reference the fields, and the golden files.

**Support a new agent.** Add an installer in `prism/integrations/` that only writes files and
config, is idempotent, backs up what it modifies, and is fully removed by
`prism uninstall-integration`. Add snapshot tests for the files it writes.

**Record a design decision.** Add `docs/adr/NNNN-title.md` describing the context, the decision
and the alternatives considered.

## Commits and pull requests

- Keep commits focused: one logical change per commit, with a message that explains *why*.
- Use a short type prefix: `feat`, `fix`, `perf`, `refactor`, `test`, `docs`, `build`, `chore`,
  optionally with a scope, for example `fix(discovery): skip minified bundles`.
- Pull requests should describe the problem, the approach, how it was tested, and any change to
  artifacts, schemas or agent-facing text. Fill in the pull request template.
- Don't commit generated caches (`.aicontext/cache/`), virtual environments or `node_modules`.

## Reporting bugs and requesting features

Use the issue templates. For bugs, include `prism --version`, your OS and Python version, the
command you ran, what you expected, what happened, and the output of `prism doctor` when setup
is involved. Never paste secrets or private source code into an issue.

Security problems should be reported privately; see [SECURITY.md](SECURITY.md).
