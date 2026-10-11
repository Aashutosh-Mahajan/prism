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
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from prism.cache_cleanup import TEE_KEEP
from prism.core.errors import UserError

MIN_LINES = 60  # shorter output is already cheap and is printed unchanged
CONTEXT = 3  # lines kept before and after every failure line
HEAD, TAIL = 25, 40  # kept from an unrecognised, very long output
MAX_UNRECOGNISED = 200

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


def save_tee(root: Path, command: str, text: str, *, raw: bytes | None = None) -> Path | None:
    from prism.cache_cleanup import TEE_BYTES, _safe_directory

    directory = tee_dir(root)
    if not _safe_directory(directory):
        return None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%H%M%S")
        payload = raw if raw is not None else text.encode("utf-8", "replace")
        if len(payload) > TEE_BYTES - 16384:
            return None  # preserve raw stdout rather than offer an unrecoverable log
        digest = hashlib.sha256(command.encode("utf-8", "replace") + b"\0" + payload).hexdigest()[
            :8
        ]
        path = directory / f"{stamp}-{digest}.txt"
        if path.is_symlink():
            return None
        path.write_bytes(raw if raw is not None else text.encode("utf-8", "replace"))
        from prism.cache_cleanup import collect_tee

        collect_tee(root)
        return path if path.is_file() else None
    except OSError:
        return None


def saved_saving(root: Path) -> tuple[int, float] | None:
    """Measured rendered-character savings; never infer a command from its log text."""
    before = after = count = 0
    directory = tee_dir(root)
    for path in sorted(directory.glob("*.meta.json"))[-TEE_KEEP:]:
        try:
            if path.is_symlink() or path.stat().st_size > 16384:
                continue
            row = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(row, dict):
                continue
            incoming, outgoing = row.get("characters_in"), row.get("characters_out")
            if (
                not all(
                    isinstance(value, int) and not isinstance(value, bool) and value >= 0
                    for value in (incoming, outgoing)
                )
                or not incoming
            ):
                continue
            assert isinstance(incoming, int) and isinstance(outgoing, int)
            before += incoming
            after += outgoing
            count += 1
        except (OSError, ValueError):
            continue
    return (count, 100 * (before - after) / before) if before else None


def show_tee(
    root: Path,
    identity: str,
    *,
    grep: str | None = None,
    around: int | None = None,
    context: int = 3,
    tail: int | None = None,
    cap: int = 12000,
) -> str:
    """Read saved output without running its command; line numbers are one-based."""
    if not re.fullmatch(r"\d{6}-[0-9a-f]{8}", identity):
        raise UserError("invalid saved-output id")
    if not 128 <= cap <= 64000 or not 0 <= context <= 100:
        raise UserError("cap must be 128–64000 characters and context 0–100 lines")
    if sum(value is not None for value in (grep, around, tail)) > 1:
        raise UserError("choose one of --grep, --around or --tail")
    if (around is not None and around < 1) or (tail is not None and tail < 1):
        raise UserError("line and tail counts must be positive")
    path = tee_dir(root) / f"{identity}.txt"
    if path.is_symlink():
        raise UserError("saved output must be a regular local file")
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise UserError("saved output is unavailable") from exc
    lines = text.splitlines(keepends=True)
    if grep is not None:
        selected = [(i, line) for i, line in enumerate(lines, 1) if grep in line]
    elif around is not None:
        selected = list(enumerate(lines, 1))[max(0, around - context - 1) : around + context]
    elif tail is not None:
        selected = list(enumerate(lines, 1))[-tail:]
    else:
        selected = []
    if any(value is not None for value in (grep, around, tail)):
        text = "".join(f"{number}: {line}" for number, line in selected)
    if len(text) <= cap:
        return text
    footer = f"\n[truncated; use prism filter --show {identity} --around <line>]\n"
    clipped = text[: cap - len(footer)]
    if "\n" in clipped:
        clipped = clipped.rsplit("\n", 1)[0]
    return clipped + footer


def run_filtered(root: Path, command: list[str]) -> int:
    """Run `command` (through the shell, as an agent would), print the filtered output."""
    shell_command = command[0] if len(command) == 1 else subprocess.list2cmdline(command)
    started = time.monotonic()
    proc = subprocess.run(
        command[0] if len(command) == 1 else command,
        shell=len(command) == 1,
        cwd=Path.cwd(),
        capture_output=True,
    )
    raw = (proc.stdout or b"") + (proc.stderr or b"")
    try:
        from prism.navigator.test_timing import record_full_suite

        record_full_suite(root, shell_command, time.monotonic() - started)
    except OSError:
        pass
    combined = raw.decode("utf-8", "replace")
    result = filter_output(shell_command, combined)
    if result.lines_out >= result.lines_in:
        sys.stdout.buffer.write(raw)
        return proc.returncode
    tee = save_tee(root, shell_command, combined, raw=raw)
    if tee is None:
        sys.stdout.buffer.write(raw)
        return proc.returncode  # never trim data that cannot be recovered
    rendered = (
        result.text
        + "\n"
        + (
            f"[prism filter: {result.lines_in} lines → {result.lines_out}"
            + f"; full output: {tee}"
            + "]\n"
        )
    )
    rendered += f"Full output: prism filter --show {tee.stem}\n"
    sys.stdout.buffer.write(rendered.encode("utf-8"))
    try:
        from prism.writers.json_writer import write_json

        write_json(
            tee.with_suffix(".meta.json"),
            {
                "family": result.family,
                "characters_in": len(combined),
                "characters_out": len(rendered),
                "exit_code": proc.returncode,
                "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
                "measurement": "rendered command output characters; not agent tokens or billing",
                "recovery_id": tee.stem,
            },
        )
        from prism.cache_cleanup import collect_tee

        collect_tee(root)
    except OSError:
        pass  # measurement failure does not discard the recoverable output
    return proc.returncode
