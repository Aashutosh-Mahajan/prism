# Read long shell output once

Run long test, build and log commands as `prism filter -- <cmd>`. Exit codes
survive filtering. If saving the complete output fails, PRISM prints it all.
No automatic shell rewriting hook is installed; see ADR 0007.

Trimmed output ends with `Full output: prism filter --show <id>`. Read a saved
log without rerunning the command:

```sh
prism filter --show 120000-abcd1234 --grep ERROR
prism filter --show 120000-abcd1234 --around 1501 -C 3
prism filter --show 120000-abcd1234 --tail 20
prism filter --show 120000-abcd1234 --cap 64000
```

Grep is a literal match. Line numbers start at one. Select one query at a time;
the default character cap is 12,000. Complete retrieval preserves UTF-8 bytes
and line endings. Binary or non-UTF-8 logs remain available in the saved file.
The local tee cache keeps at most forty logs, 32 MiB including metadata, and
thirty days of history. Oversized output is printed in full. Doctor reports
cache size and measured character savings including the footer.

Run `prism cache gc` to apply the limits now. Use `--keep`, `--max-bytes`, and
`--age-days` to tighten a cleanup; `--json` reports removed files and bytes.
Cleanup only removes recognized saved-log files and their metadata. It leaves
the index, notes, other caches, and user files intact, and skips symlink paths.
