"""`prism filter -- <command>`: run a command and print only the part of its output that matters.

Test runs, builds and package installs print thousands of lines of which an agent needs the few
that failed. The command runs unchanged; its combined output is saved in full under
`.aicontext/cache/tee/` and a shortened form is printed, with the path of the full output on the
last line. The exit status is the command's own.

Safety rules (docs/adr/0004-output-filtering.md):
* Output shorter than `MIN_LINES` is printed unchanged.
* A line that looks like a failure is never dropped, nor are the `CONTEXT` lines around it.
* The known-noise patterns of a command family only ever remove lines that are not failures.
* Anything unrecognised is kept (head, tail and failure lines when it is very long).
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

MIN_LINES = 60  # shorter output is already cheap and is printed unchanged
CONTEXT = 3  # lines kept before and after every failure line
HEAD, TAIL = 25, 40  # kept from an unrecognised, very long output
MAX_UNRECOGNISED = 200
TEE_KEEP = 40  # tee files older than this many newest are removed

FAILURE = re.compile(
    r"(?i)\b(fail(?:ed|s|ure|ures)?|error(?:s)?|exception|traceback|assert(?:ion)?(?:error)?|"
    r"panic|fatal|denied|cannot|can't|unable|not found|timed? ?out|segmentation|abort(?:ed)?|"
    r"npm err|warn(?:ing)?s?|deprecat\w*)\b|✗|✖|×|\[E\]|^E\s|^>\s|FAILED|ERROR"
)

# Per command family: lines that are pure progress or banner text. Lines matching FAILURE are
# kept even if they also match a noise pattern.
_PYTEST_NOISE = re.compile(
    r"^(\.|[.sxFEpP]+\s*\[\s*\d+%\]|platform |rootdir:|configfile:|plugins:|collected \d+|cachedir:|"
    r"=+ test session starts =+|[\w/\\.\-]+\.py [.sxFE]+(\s+\[\s*\d+%\])?$)"
)
_JEST_NOISE = re.compile(
    r"^\s*(PASS |✓|√|\s*[✓√]\s|Test Suites: .* passed$|Snapshots:|Time:|Ran all)"
)
_FLUTTER_NOISE = re.compile(r"^\d\d:\d\d\s\+\d+(\s~\d+)?:\s.*(?<!failed)$|^\s*$")
_GO_NOISE = re.compile(r"^(=== (RUN|PAUSE|CONT)|--- PASS|ok\s+\S+\s+[\d.]+s|PASS$)")
_CARGO_NOISE = re.compile(
    r"^(test .* \.\.\. ok$|\s+(Compiling|Downloaded|Downloading|Fresh) |running \d+ tests)"
)
_NPM_NOISE = re.compile(
    r"^(npm (http|timing|verb|info|notice)|added \d+ packages|\s*[\u2800-\u28ff|/\\-]\s*$|"
    r"\s*(Downloading|Fetching|Resolving|Progress)[: ]|up to date)"
)
_GIT_NOISE = re.compile(r"^(index [0-9a-f]+\.\.[0-9a-f]+|Merge: |\s*$)")

FAMILIES: tuple[tuple[str, re.Pattern[str], re.Pattern[str]], ...] = (
    ("pytest", re.compile(r"\b(pytest|py\.test|manage\.py test|unittest)\b"), _PYTEST_NOISE),
    (
        "jest",
        re.compile(r"\b(jest|vitest|mocha)\b|\b(npm|yarn|pnpm)\s+(run\s+)?test\b"),
        _JEST_NOISE,
    ),
    ("flutter", re.compile(r"\bflutter\s+(test|analyze|build)\b|\bdart\s+test\b"), _FLUTTER_NOISE),
    ("go", re.compile(r"\bgo\s+(test|build|vet)\b"), _GO_NOISE),
    ("cargo", re.compile(r"\bcargo\s+(test|build|check|clippy)\b"), _CARGO_NOISE),
    ("npm", re.compile(r"\b(npm|yarn|pnpm)\s+(install|ci|i|add|run\s+build|build)\b"), _NPM_NOISE),
    ("git", re.compile(r"\bgit\s+(log|show|diff|status)\b"), _GIT_NOISE),
)


@dataclass
class Filtered:
    text: str
    family: str
    lines_in: int
    lines_out: int


def _family(command: str) -> tuple[str, re.Pattern[str] | None]:
    for name, pattern, noise in FAMILIES:
        if pattern.search(command):
            return name, noise
    return "other", None


def _keep_failures(lines: list[str]) -> set[int]:
    keep: set[int] = set()
    for i, line in enumerate(lines):
        if FAILURE.search(line):
            keep.update(range(max(0, i - CONTEXT), min(len(lines), i + CONTEXT + 1)))
    return keep


def _pytest_sections(lines: list[str]) -> set[int]:
    """Whole FAILURES / ERRORS / short-summary sections and the final result line."""
    keep: set[int] = set()
    inside = False
    for i, line in enumerate(lines):
        header = re.match(r"^=+ (.+?) =+$", line)
        if header:
            title = header.group(1).lower()
            inside = any(k in title for k in ("failures", "errors", "short test summary"))
            if not inside and re.search(r"\d+ (passed|failed|error)", title):
                keep.add(i)
        if inside:
            keep.add(i)
    return keep


def filter_output(command: str, text: str) -> Filtered:
    lines = text.splitlines()
    family, noise = _family(command)
    if len(lines) < MIN_LINES:
        return Filtered(text, family, len(lines), len(lines))
    keep = _keep_failures(lines)
    if family == "pytest":
        keep |= _pytest_sections(lines)
    if noise is not None:
        kept = [
            line
            for i, line in enumerate(lines)
            if i in keep or (not noise.search(line) and line.strip())
        ]
    else:
        kept = list(lines)
    if len(kept) > MAX_UNRECOGNISED and family != "git":  # a diff or log is read as a whole
        kept_lines = set(kept)
        indices = {i for i, line in enumerate(lines) if line in kept_lines}
        indices &= keep | set(range(HEAD)) | set(range(max(0, len(lines) - TAIL), len(lines)))
        kept = [lines[i] for i in sorted(indices)]
    omitted = len(lines) - len(kept)
    out = "\n".join(kept)
    return Filtered(out, family, len(lines), len(kept) + (1 if omitted else 0))


def tee_dir(root: Path) -> Path:
    from prism.consent import cache_root

    return cache_root(root) / "tee"


def save_tee(root: Path, command: str, text: str) -> Path | None:
    directory = tee_dir(root)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%H%M%S")
        digest = hashlib.sha256((command + text).encode("utf-8", "replace")).hexdigest()[:8]
        path = directory / f"{stamp}-{digest}.txt"
        path.write_text(text, encoding="utf-8", errors="replace")
        files = sorted(directory.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[TEE_KEEP:]:
            old.unlink(missing_ok=True)
        return path
    except OSError:
        return None


def run_filtered(root: Path, command: list[str]) -> int:
    """Run `command` (through the shell, as an agent would), print the filtered output."""
    shell_command = command[0] if len(command) == 1 else subprocess.list2cmdline(command)
    proc = subprocess.run(
        shell_command,
        shell=True,
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    combined = (proc.stdout or "") + (proc.stderr or "")
    result = filter_output(shell_command, combined)
    if result.lines_out >= result.lines_in:
        sys.stdout.write(combined)
        return proc.returncode
    tee = save_tee(root, shell_command, combined)
    sys.stdout.write(result.text + "\n")
    sys.stdout.write(
        f"[prism filter: {result.lines_in} lines → {result.lines_out}"
        + (f"; full output: {tee}" if tee else "")
        + "]\n"
    )
    return proc.returncode
