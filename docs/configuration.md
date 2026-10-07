# Configuration

PRISM works with no configuration. Everything here is optional.

## Project settings

Put settings in `prism.toml` at the repository root, or under `[tool.prism]` in
`pyproject.toml`. If both exist, `prism.toml` wins.

```toml
# pyproject.toml
[tool.prism]
ignore = ["generated/", "*.pb.py"]   # gitignore syntax, on top of .gitignore and .prismignore
max_file_size = 1000000              # bytes; larger files are skipped
source_roots = ["src"]               # stripped when deriving module names
test_dirs = ["tests", "test"]        # folders whose files count as tests
drift_threshold = 8                  # drift points before a brief section is marked stale
semantic_model = "/models/all-MiniLM-L6-v2"   # local model path for `search --semantic`
prompt_context = true                # let the prompt hook add the code a request needs
prompt_budget = 1200                 # tokens (chars/4) the prompt hook may add, 128-8000
```

| Key | Type | Default | Effect |
|---|---|---|---|
| `ignore` | list of strings | `[]` | Extra ignore patterns in `.gitignore` syntax |
| `max_file_size` | positive integer | `1000000` | Files larger than this many bytes are not indexed |
| `source_roots` | list of strings | `["src"]` | Prefixes removed from paths when deriving module ids (`src/shop/cart.py` → `shop.cart`) |
| `test_dirs` | list of strings | `["tests", "test"]` | Directory names whose files are treated as tests |
| `drift_threshold` | positive integer | `8` | Score at which an `AGENTS.md` section or module summary becomes stale |
| `semantic_model` | string | `sentence-transformers/all-MiniLM-L6-v2` | Embedding model for `--semantic`; must already be on disk, PRISM never downloads |
| `prompt_context` | boolean | `true` | `false` stops `prism hook user-prompt` from adding anything to prompts |
| `prompt_budget` | integer | `1200` | Most the prompt hook adds to one prompt, as `ceil(characters/4)` (128-8000) |

Invalid values stop the command with a clear error rather than being silently ignored.

## Ignoring files

PRISM combines, in order:

1. **Built-in ignores:** version-control folders, `.aicontext/`, virtual environments,
   `node_modules`, caches, `build`, `dist`, `target`, `coverage`, `vendor`, editor folders and
   `*.egg-info`.
2. **`.gitignore` files**, each scoped to its own directory, with `!pattern` re-includes honoured
   the way git does.
3. **`.prismignore`** at the root, in the same syntax, for things you want in git but not in the
   index.
4. **`ignore`** from the configuration above.

Binary files, files over `max_file_size`, minified bundles (`*.min.js`, `*.bundle.js`, source
maps, or JavaScript/TypeScript that reads as minified) and unrecognised file types are skipped
automatically.

## Languages

| Language | Parser | Install |
|---|---|---|
| Python | stdlib `ast` | built in |
| JavaScript, TypeScript (incl. JSX/TSX) | tree-sitter | `pip install "prism-ctx[treesitter]"` |
| Go, Java | tree-sitter | `pip install "prism-ctx[treesitter]"` |
| Kotlin, Rust, Ruby, PHP, C#, C, C++, Swift, Scala, shell, SQL | none yet | counted in the language stats, not parsed |

`prism doctor` shows which languages were found and which are parsed.

## Environment variables

| Variable | Effect |
|---|---|
| `PRISM_CONFIG_HOME` | Where the per-user consent registry lives (default `~/.config/prism`). Point it at a scratch folder for experiments and tests. |
| `PRISM_VIEWER_LOG=1` | Log every viewer HTTP request to the terminal. |
| `PRISM_UPDATE_GOLDEN=1` | Development only: regenerate golden files when running the tests. |
| `PRISM_HOOK_NO_EXIT=1` | Development only: let hook commands return normally instead of exiting the process, for in-process testing. |
| `PRISM_HOOK_SYNC=1` | Make `prism hook post-edit` wait for the index update instead of starting it in a detached process. |
| `PRISM_PROMPT_CONTEXT=0` | Switch off what `prism hook user-prompt` adds to prompts, for you, in every repository. |
| `PRISM_MCP_PROFILE=full` | Expose every MCP tool (default `lean`: `prism_status`, `prism_task`, `prism_context`, `prism_impact`). |
| `PRISM_SESSION` | A session id for `prism task`: code already returned in this session comes back as a reference. |

## Per-user state

| File | Contents |
|---|---|
| `~/.config/prism/repos.toml` | Which repositories PRISM is enabled or paused in, for you |
| Your agent's global instructions (for example `~/.claude/CLAUDE.md`) | Only if you ran `prism install --global` |

Nothing else is written outside the repositories you enable.
