"""`prism view`: a local, token-protected HTTP server for the graph viewer.

Security model (CLAUDE.md 11.4):
- binds to 127.0.0.1 only, on a random free port by default;
- every request needs the per-session token (query `token=` once, then an
  HttpOnly SameSite=Strict cookie, or the `X-Prism-Token` header);
- the Host header must be the loopback address (DNS-rebinding defence);
- no endpoint writes source files or runs commands. The only writes are the
  layout and saved views in `.aicontext/cache/`.
Live updates are pushed over Server-Sent Events.
"""

from __future__ import annotations

import contextlib
import hmac
import json
import mimetypes
import os
import queue
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit

from prism.core.errors import PrismError
from prism.core.paths import AICONTEXT, manifest_path
from prism.viewer.api import ViewerBackend
from prism.writers.activity import activity_path
from prism.writers.json_writer import write_json

DIST = Path(__file__).resolve().parent.parent / "viewer_dist"
MAX_BODY = 5 * 1024 * 1024
POLL_SECONDS = 0.4
HEARTBEAT_SECONDS = 15.0
COOKIE = "prism_token"
CSP = (
    "default-src 'self'; script-src 'self' blob:; worker-src 'self' blob:; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'"
)


class EventHub:
    """Fans index/activity events out to connected SSE clients."""

    def __init__(self) -> None:
        self._clients: list[queue.Queue[str]] = []
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue[str]:
        q: queue.Queue[str] = queue.Queue(maxsize=200)
        with self._lock:
            self._clients.append(q)
        return q

    def unsubscribe(self, q: queue.Queue[str]) -> None:
        with self._lock:
            if q in self._clients:
                self._clients.remove(q)

    def publish(self, event: str, data: dict[str, Any]) -> None:
        message = f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"
        with self._lock:
            for q in list(self._clients):
                with contextlib.suppress(queue.Full):
                    q.put_nowait(message)


class Watcher(threading.Thread):
    """Polls the manifest and the activity log; publishes deltas."""

    def __init__(self, root: Path, backend: ViewerBackend, hub: EventHub) -> None:
        super().__init__(daemon=True)
        self.root = root
        self.backend = backend
        self.hub = hub
        self.stop = threading.Event()

    def _stat(self, path: Path) -> tuple[float, int]:
        try:
            st = path.stat()
            return (st.st_mtime, st.st_size)
        except OSError:
            return (0.0, 0)

    def _file_hashes(self) -> dict[str, str]:
        try:
            data = json.loads(manifest_path(self.root).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {p: e.get("sha256", "") for p, e in data.get("files", {}).items()}

    def run(self) -> None:
        manifest_stat = self._stat(manifest_path(self.root))
        files = self._file_hashes()
        activity = activity_path(self.root)
        offset = self._stat(activity)[1]
        symbols = set(self.backend.model().symbols)
        while not self.stop.wait(POLL_SECONDS):
            st = self._stat(manifest_path(self.root))
            if st != manifest_stat:
                manifest_stat = st
                new_files = self._file_hashes()
                try:
                    model = self.backend.model()
                except PrismError:
                    continue
                new_symbols = set(model.symbols)
                changed_files = sorted(
                    p for p in new_files if p in files and new_files[p] != files[p]
                )
                changed_set = set(changed_files)
                self.hub.publish(
                    "index",
                    {
                        "added": sorted((set(new_files) - set(files)) | (new_symbols - symbols)),
                        "removed": sorted((set(files) - set(new_files)) | (symbols - new_symbols)),
                        "changed": changed_files
                        + sorted(
                            s
                            for s in new_symbols & symbols
                            if model.symbols[s]["file"] in changed_set
                        ),
                    },
                )
                files, symbols = new_files, new_symbols
            size = self._stat(activity)[1]
            if size < offset:
                offset = 0  # the log was truncated
            if size > offset:
                try:
                    with activity.open("r", encoding="utf-8") as fh:
                        fh.seek(offset)
                        chunk = fh.read()
                        offset = fh.tell()
                except OSError:
                    continue
                for line in chunk.splitlines():
                    with contextlib.suppress(ValueError):
                        self.hub.publish("activity", json.loads(line))


def make_handler(
    backend: ViewerBackend, hub: EventHub, token: str, port_ref: list[int]
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "prism-viewer"
        sys_version = ""

        def log_message(self, format: str, *args: Any) -> None:
            if os.environ.get("PRISM_VIEWER_LOG") == "1":
                super().log_message(format, *args)

        # --- helpers ------------------------------------------------------------

        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").lower()
            port = port_ref[0]
            return host in (f"127.0.0.1:{port}", f"localhost:{port}", "127.0.0.1", "localhost")

        def _token_ok(self, query: dict[str, str]) -> bool:
            candidates = [query.get("token", ""), self.headers.get("X-Prism-Token", "")]
            for part in (self.headers.get("Cookie") or "").split(";"):
                name, _, value = part.strip().partition("=")
                if name == COOKIE:
                    candidates.append(value)
            return any(c and hmac.compare_digest(c, token) for c in candidates)

        def _send(
            self, status: int, body: bytes, ctype: str, extra: dict[str, str] | None = None
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status: int, data: Any) -> None:
            self._send(
                status,
                json.dumps(data, ensure_ascii=False).encode("utf-8"),
                "application/json; charset=utf-8",
            )

        def _error(self, exc: Exception) -> None:
            if isinstance(exc, PrismError):
                status = (
                    404
                    if exc.code == "not_found"
                    else (409 if exc.code == "ambiguous_target" else 400)
                )
                if exc.code == "index_missing":
                    status = 503
                self._json(status, exc.to_dict())
            else:
                self._json(500, {"error": "internal_error", "message": type(exc).__name__})

        def _gate(self) -> tuple[str, dict[str, str]] | None:
            parts = urlsplit(self.path)
            query = dict(parse_qsl(parts.query))
            if not self._host_ok():
                self._json(403, {"error": "forbidden", "message": "bad Host header"})
                return None
            if not self._token_ok(query):
                self._json(401, {"error": "unauthorized", "message": "missing or invalid token"})
                return None
            return unquote(parts.path), query

        # --- routes ---------------------------------------------------------------

        def do_HEAD(self) -> None:
            self.do_GET()

        def do_GET(self) -> None:
            gated = self._gate()
            if gated is None:
                return
            path, query = gated
            if "token" in query and not path.startswith("/api/"):
                # Trade the one-time URL token for a cookie, then drop it from the address bar.
                rest = {k: v for k, v in query.items() if k != "token"}
                location = path + ("?" + urlencode(rest) if rest else "")
                self.send_response(302)
                self.send_header("Location", location)
                self.send_header(
                    "Set-Cookie", f"{COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/"
                )
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            try:
                if path == "/api/events":
                    self._events()
                    return
                if path.startswith("/api/"):
                    self._json(200, self._api_get(path, query))
                    return
                self._static(path)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as exc:
                self._error(exc)

        def do_POST(self) -> None:
            gated = self._gate()
            if gated is None:
                return
            path, _ = gated
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                self._json(413, {"error": "too_large"})
                return
            if (self.headers.get("Content-Type") or "").split(";")[0] != "application/json":
                self._json(415, {"error": "unsupported_media_type"})
                return
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                if path == "/api/layout":
                    self._json(200, backend.save_layout(body))
                elif path == "/api/views":
                    self._json(200, backend.save_view(body))
                else:
                    self._json(404, {"error": "not_found"})
            except ValueError:
                self._json(400, {"error": "bad_json"})
            except Exception as exc:
                self._error(exc)

        def _api_get(self, path: str, q: dict[str, str]) -> Any:
            if path == "/api/meta":
                return backend.meta()
            if path == "/api/graph":
                return backend.graph(q)
            if path.startswith("/api/node/"):
                return backend.node(path[len("/api/node/") :])
            if path == "/api/search":
                return backend.search(q)
            if path == "/api/path":
                return backend.path(q)
            if path.startswith("/api/impact/"):
                return backend.impact(path[len("/api/impact/") :], q)
            if path == "/api/diff":
                return backend.diff(q)
            if path == "/api/layout":
                return backend.get_layout()
            if path == "/api/views":
                return backend.list_views()
            from prism.core.errors import NotFoundError

            raise NotFoundError(f"no endpoint {path}")

        def _static(self, path: str) -> None:
            rel = "index.html" if path in ("/", "") else path.lstrip("/")
            target = (DIST / rel).resolve()
            if DIST.resolve() not in target.parents and target != DIST.resolve() / "index.html":
                self._json(404, {"error": "not_found"})
                return
            if not target.is_file():
                if not (DIST / "index.html").is_file():
                    self._send(
                        500,
                        b"viewer bundle missing: build it with `npm run build` in viewer/",
                        "text/plain; charset=utf-8",
                    )
                    return
                self._json(404, {"error": "not_found"})
                return
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript",):
                ctype += "; charset=utf-8"
            self._send(200, target.read_bytes(), ctype)

        def _events(self) -> None:
            q = hub.subscribe()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()
                self.wfile.write(b"retry: 2000\n\n")
                self.wfile.flush()
                while True:
                    try:
                        message = q.get(timeout=HEARTBEAT_SECONDS)
                    except queue.Empty:
                        message = ": ping\n\n"
                    self.wfile.write(message.encode("utf-8"))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                hub.unsubscribe(q)

    return Handler


class ViewerServer:
    def __init__(self, root: Path, port: int = 0, token: str | None = None) -> None:
        self.root = root.resolve()
        self.token = token or secrets.token_urlsafe(24)
        self.backend = ViewerBackend(self.root)
        self.backend.model()  # fail fast if there is no index
        self.hub = EventHub()
        self._port_ref = [0]
        handler = make_handler(self.backend, self.hub, self.token, self._port_ref)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
        self.httpd.daemon_threads = True
        self.port = int(self.httpd.server_address[1])
        self._port_ref[0] = self.port
        self.watcher = Watcher(self.root, self.backend, self.hub)
        self._thread: threading.Thread | None = None

    def url(self, focus: str | None = None, depth: int | None = None) -> str:
        params = {"token": self.token}
        if focus:
            params["focus"] = focus
        if depth:
            params["depth"] = str(depth)
        return f"http://127.0.0.1:{self.port}/?" + "&".join(
            f"{k}={quote(v)}" for k, v in params.items()
        )

    def _runtime_file(self) -> Path:
        return self.root / AICONTEXT / "cache" / "viewer.json"

    def start(self) -> None:
        self.watcher.start()
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()
        write_json(
            self._runtime_file(),
            {"port": self.port, "pid": os.getpid(), "token": self.token, "started": time.time()},
        )

    def serve_forever(self) -> None:
        self.watcher.start()
        write_json(
            self._runtime_file(),
            {"port": self.port, "pid": os.getpid(), "token": self.token, "started": time.time()},
        )
        try:
            self.httpd.serve_forever()
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        self.watcher.stop.set()
        self.httpd.shutdown()
        self.httpd.server_close()
        with contextlib.suppress(OSError):
            self._runtime_file().unlink()


def running_viewer(root: Path) -> dict[str, Any] | None:
    """The viewer already serving this repo, if any (used by `prism_graph_view_url`)."""
    path = root / AICONTEXT / "cache" / "viewer.json"
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    import socket

    try:
        with socket.create_connection(("127.0.0.1", int(info["port"])), timeout=0.3):
            return dict(info)
    except OSError:
        return None
