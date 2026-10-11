"""Fresh-process Windows latency, with and without an existing PRISM daemon."""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def measure(base: Path, output: Path, repetitions: int, launcher: str | None = None) -> None:
    os.environ.update(PRISM_CONFIG_HOME=str(base / "config"), PRISM_SEMANTIC="0")
    repo = base / "repo"
    if not repo.exists():
        repo.mkdir(parents=True)
        archive = subprocess.run(
            ["git", "archive", "--format=zip", "HEAD"], cwd=ROOT, capture_output=True, check=True
        ).stdout
        with zipfile.ZipFile(io.BytesIO(archive)) as files:
            for entry in files.infolist():
                path = repo / entry.filename
                if not path.resolve().is_relative_to(repo.resolve()):
                    raise ValueError("archive escapes benchmark copy")
                if not entry.is_dir():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(files.read(entry))
        subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
        subprocess.run(["git", "add", "--all"], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=PRISM benchmark",
                "-c",
                "user.email=benchmark@localhost",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "-qm",
                "Latency fixture",
            ],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        from prism.lifecycle import apply_init, plan_init, scan

        apply_init(plan_init(repo))
        scan(repo)
    from prism.navigator import daemon

    executable = launcher or shutil.which("prism")
    if executable is None:
        raise ValueError("prism executable is missing")
    commands = {
        "find": ["find", "def save_tee", "--budget", "500"],
        "task": ["task", "Where is saved shell output implemented?"],
        "user_prompt": ["hook", "user-prompt"],
        "session_start": ["hook", "session-start"],
        "post_edit": ["hook", "post-edit"],
    }
    results = {}
    env = dict(os.environ, PYTHONUTF8="1", PYTHONPATH=str(ROOT))
    os.environ["PYTHONPATH"] = str(ROOT)
    for temperature in ("without_daemon", "with_daemon"):
        if temperature == "without_daemon":
            daemon.stop(repo)
            env["PRISM_DAEMON"] = "0"
        else:
            env.pop("PRISM_DAEMON", None)
            os.environ.pop("PRISM_DAEMON", None)
            daemon.ensure_running(repo)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if (
                    daemon.ask(
                        repo, {"op": "task", "query": "Where is saved shell output implemented?"}
                    )
                    is not None
                ):
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError("warm daemon did not become ready")
        for name, command in commands.items():
            timings = []
            lengths = []
            for repetition in range(3 if temperature == "without_daemon" else repetitions):
                payload = {
                    "cwd": str(repo),
                    "session_id": f"latency-{output.stem}-{name}-{repetition}",
                    "source": "startup",
                    "prompt": "Where is saved shell output implemented?",
                    "tool_name": "apply_patch",
                    "tool_input": {"file_path": str(repo / "prism/outputfilter.py")},
                }
                started = time.perf_counter()
                result = subprocess.run(
                    [executable, *command],
                    cwd=repo,
                    env=env,
                    input=json.dumps(payload).encode() if command[0] == "hook" else None,
                    capture_output=True,
                    timeout=30,
                )
                elapsed = time.perf_counter() - started
                if result.returncode:
                    raise RuntimeError(
                        f"{name} failed: {result.stderr.decode('utf-8', 'replace')[:500]}"
                    )
                timings.append(elapsed * 1000)
                lengths.append(len(result.stdout))
            ordered = sorted(timings)
            results[temperature + "/" + name] = {
                "milliseconds": timings,
                "median_ms": ordered[len(ordered) // 2],
                "p95_ms": ordered[math.ceil(0.95 * len(ordered)) - 1],
                "output_bytes": lengths,
            }
            print(temperature, name, results[temperature + "/" + name]["p95_ms"], flush=True)
    daemon.stop(repo)
    with output.with_suffix(".imports.txt").open("wb") as log:
        subprocess.run(
            [
                sys.executable,
                "-X",
                "importtime",
                "-c",
                "import sys;sys.path.insert(0, "
                + repr(str(ROOT))
                + ");from prism.entry import main;main()",
                "find",
                "def save_tee",
            ],
            cwd=repo,
            env=dict(env, PRISM_DAEMON="0"),
            stdout=subprocess.DEVNULL,
            stderr=log,
            check=True,
        )
    output.write_text(
        json.dumps(
            {
                "platform": sys.platform,
                "python": sys.version,
                "executable": executable,
                "fixture_revision": subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    check=True,
                ).stdout.strip(),
                "working_tree_dirty": bool(
                    subprocess.run(
                        ["git", "diff", "--name-only"], cwd=ROOT, capture_output=True, check=True
                    ).stdout
                ),
                "note": "Fresh processes; filesystem caches are not flushed. Post-edit is an unchanged-file event. Warm daemon was explicitly prepared in the disposable copy.",
                "results": results,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=20)
    parser.add_argument("--executable", help="Freshly installed prism console launcher")
    args = parser.parse_args()
    measure(args.base.resolve(), args.output.resolve(), args.repetitions, args.executable)
