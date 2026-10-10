"""A warm local query process, so `prism task` skips Python start-up and index loading.

docs/adr/0003-warm-query-process.md. Rules it follows:
* Local IPC only: a named pipe on Windows, a Unix socket elsewhere, authenticated with a random
  per-process key kept in `.aicontext/cache/daemon.json`. No TCP port is ever opened.
* It exists only for a repo that is enabled and not paused for this user. It is started by a
  `prism task` call (never by `init`, `scan`, hooks or anything else), exits after ten idle
  minutes, and exits when consent is withdrawn or PRISM is paused.
* Anything unexpected makes the client fall back to answering in-process, byte-identically.
* Switch off with `PRISM_DAEMON=0` or `daemon = false` in `[tool.prism]`.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import secrets
import subprocess
import sys
import threading
import time
from multiprocessing.connection import Client, Listener
from pathlib import Path
from typing import Any

IDLE_SECONDS = 600.0
WATCH_SECONDS = 10.0
CHECK_INTERVAL = 1.0  # the working tree is re-checked at most this often (verify always checks)
SPAWN_COOLDOWN = 30.0
CONNECT_TIMEOUT = 2.0
INFO = "daemon.json"
SPAWN_MARK = "daemon.spawning"


def _cache(root: Path) -> Path:
    from prism.consent import cache_root

    return cache_root(root)


def _address(root: Path) -> str:
    digest = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:16]
    if sys.platform == "win32":
        return rf"\\.\pipe\prism-{digest}"
    return str(_cache(root) / "daemon.sock")


def enabled(root: Path) -> bool:
    """Is a warm process allowed for this repo and this user right now?"""
    if os.environ.get("PRISM_DAEMON") == "0":
        return False
    try:
        from prism.config import load_config
        from prism.consent import RepoState, repo_state
        from prism.writers.manifest import load_manifest

        if load_config(root).extra.get("daemon", True) is False:
            return False
        manifest = load_manifest(root)
        return (
            manifest is not None and repo_state(root, manifest.get("repo_id")) is RepoState.ENABLED
        )
    except Exception:
        return False


def _read_info(root: Path) -> dict[str, Any] | None:
    try:
        data = json.loads((_cache(root) / INFO).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and "key" in data and "address" in data else None


# --- client ---------------------------------------------------------------------------


def _call(info: dict[str, Any], request: dict[str, Any]) -> dict[str, Any] | None:
    result: list[dict[str, Any]] = []

    def go() -> None:
        try:
            family = "AF_PIPE" if sys.platform == "win32" else "AF_UNIX"
            conn = Client(info["address"], family=family, authkey=bytes.fromhex(info["key"]))
            with contextlib.closing(conn):
                conn.send_bytes(json.dumps(request).encode("utf-8"))
                reply = json.loads(conn.recv_bytes().decode("utf-8"))
                if isinstance(reply, dict):
                    result.append(reply)
        except Exception:
            return

    thread = threading.Thread(target=go, daemon=True)
    thread.start()
    thread.join(30.0)
    return result[0] if result else None


def ask(root: Path, request: dict[str, Any]) -> str | None:
    """The answer from a running warm process, or None (then the caller answers itself)."""
    if not enabled(root):
        return None
    info = _read_info(root)
    if info is None:
        return None
    reply = _call(info, request)
    if reply is None or not reply.get("ok") or not isinstance(reply.get("text"), str):
        return None
    return str(reply["text"])


def ensure_running(root: Path) -> None:
    """Start the warm process in the background if it is allowed and not running."""
    if not enabled(root) or _read_info(root) is not None:
        return
    mark = _cache(root) / SPAWN_MARK
    try:
        if time.time() - mark.stat().st_mtime < SPAWN_COOLDOWN:
            return
    except OSError:
        pass
    try:
        mark.parent.mkdir(parents=True, exist_ok=True)
        mark.write_text(str(os.getpid()), encoding="utf-8")
        flags = 0
        extra: dict[str, Any] = {}
        if sys.platform == "win32":
            flags = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED | NEW_GROUP | NO_WINDOW
        else:
            extra["start_new_session"] = True
        subprocess.Popen(
            [sys.executable, "-m", "prism.navigator.daemon", "serve", "--root", str(root)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=True,
            **extra,
        )
    except OSError:
        pass


def stop(root: Path) -> bool:
    """Ask a running warm process to exit. Safe to call when none runs."""
    info = _read_info(root)
    if info is None:
        return False
    reply = _call(info, {"op": "stop"})
    with contextlib.suppress(OSError):
        (_cache(root) / INFO).unlink()
    return reply is not None


def stop_quietly(root: Path) -> None:
    with contextlib.suppress(Exception):
        stop(root)


# --- server ---------------------------------------------------------------------------


class _Holder:
    """The open index, reopened when it changes, and the throttled working-tree check."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.store: Any = None
        self.checked = 0.0

    def fresh(self, force: bool) -> Any:
        from prism.navigator.freshness import refresh_if_stale
        from prism.navigator.store import IndexStore

        now = time.monotonic()
        if force or now - self.checked >= CHECK_INTERVAL:
            refresh_if_stale(self.root)
            self.checked = time.monotonic()
        if self.store is None or not self.store.is_current():
            if self.store is not None:
                self.store.close()
            self.store = IndexStore.open(self.root)
        return self.store


def _handle(holder: _Holder, request: dict[str, Any]) -> dict[str, Any]:
    from prism.navigator.taskrun import run_task

    if request.get("op") != "task":
        return {"ok": False, "error": "unknown op"}
    mode = str(request.get("mode") or "auto")
    store = holder.fresh(force=mode == "verify")
    text = run_task(
        holder.root,
        store,
        str(request["query"]),
        int(request.get("budget", 2000)),
        mode,
        request.get("session"),
        bool(request.get("json")),
        str(request.get("detail") or "full"),
    )
    return {"ok": True, "text": text}


def serve(root: Path) -> None:
    from prism.writers import task_cache

    task_cache.STAMP_TTL_SECONDS = CHECK_INTERVAL
    root = root.resolve()
    if not enabled(root):
        return
    key = secrets.token_bytes(24)
    address = _address(root)
    family = "AF_PIPE" if sys.platform == "win32" else "AF_UNIX"
    if family == "AF_UNIX":
        with contextlib.suppress(OSError):
            os.unlink(address)
    listener = Listener(address, family=family, authkey=key)
    info_path = _cache(root) / INFO
    info_path.parent.mkdir(parents=True, exist_ok=True)
    info_path.write_text(
        json.dumps({"pid": os.getpid(), "address": address, "key": key.hex()}), encoding="utf-8"
    )
    with contextlib.suppress(OSError):
        os.chmod(info_path, 0o600)
    state = {"last": time.monotonic()}

    def leave() -> None:
        with contextlib.suppress(OSError):
            info_path.unlink()
        os._exit(0)

    def watch() -> None:
        while True:
            time.sleep(WATCH_SECONDS)
            if time.monotonic() - state["last"] > IDLE_SECONDS or not enabled(root):
                leave()

    threading.Thread(target=watch, daemon=True).start()
    holder = _Holder(root)
    while True:
        try:
            conn = listener.accept()
        except Exception:
            continue
        try:
            with contextlib.closing(conn):
                request = json.loads(conn.recv_bytes().decode("utf-8"))
                state["last"] = time.monotonic()
                if isinstance(request, dict) and request.get("op") == "stop":
                    conn.send_bytes(json.dumps({"ok": True}).encode("utf-8"))
                    leave()
                try:
                    reply = _handle(holder, request)
                except Exception as exc:  # the client then answers in-process
                    reply = {"ok": False, "error": type(exc).__name__}
                conn.send_bytes(json.dumps(reply, ensure_ascii=False).encode("utf-8"))
        except Exception:
            continue


def main(argv: list[str]) -> None:
    if len(argv) >= 3 and argv[0] == "serve" and argv[1] == "--root":
        serve(Path(argv[2]))


if __name__ == "__main__":
    main(sys.argv[1:])
