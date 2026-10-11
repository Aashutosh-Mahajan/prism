# T47 cache cleanup

Adopt automatic saved-log caps: forty logs, 32 MiB including metadata, thirty
days. `prism cache gc` applies configurable stricter limits and reports removed
files and bytes. `doctor` reports total disposable-cache size. Indexes and notes
are outside the deletion set; unrecognized files and symlinks are skipped.

The 500-log experiment created 1,000 log/metadata files. With a 1,020-byte cap,
ten newest logs remained, totaling exactly 1,020 bytes; 980 files and 49,980 bytes
were removed. A second pass removed nothing. The index, notes and an owner log
retained their original bytes. Additional tests cover age expiry, orphan
metadata, oversized output and CLI reporting. Oversized output falls back to
complete stdout, preserving recovery and command status.

Twenty-eight focused cache, shell-filter and doctor tests ran: twenty-seven
passed and the Windows symlink creation case skipped because the current token
lacks that privilege. The symlink guard is exercised when symlink creation is
available. Ruff and strict mypy checks also passed.
