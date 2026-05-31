#!/usr/bin/env python3
"""Server persistente del orbe de voice-claude.

Sirve orb.html (+ vendor local de three.js) en localhost y emite por SSE:
  - el estado actual (canal confiable, no se pierde)
  - el nivel de audio (canal coalescado "ultimo valor", nunca pisa estados)

voice_claude.py hace POST /state?s=<fase> y POST /level?v=<0..1>.
Solo stdlib, sin dependencias.

Estados: idle, rec, transcribe, screen, think, speak, nueva, error, cancel.
"""
import os
import sys
import time
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

PORT = int(os.environ.get("ORB_PORT", "8777"))
TOKEN = os.environ.get("ORB_TOKEN", "")          # vacio = sin auth (local)
IDLE_TIMEOUT = 180.0                              # seg sin actividad -> vuelve a idle
HERE = Path(__file__).resolve().parent
HTML = HERE / "orb.html"
VENDOR = (HERE / "vendor").resolve()

VALID_STATES = {
    "idle", "rec", "transcribe", "screen",
    "think", "speak", "nueva", "error", "cancel",
}
MIME = {".js": "text/javascript", ".css": "text/css",
        ".html": "text/html; charset=utf-8", ".json": "application/json"}

_state = {"name": "idle"}
_clients: "set[queue.Queue]" = set()
_lock = threading.Lock()
_last_activity = time.monotonic()


def _touch() -> None:
    global _last_activity
    _last_activity = time.monotonic()


def normalize_state(name: "str | None") -> str:
    if not name:
        return "idle"
    name = name.strip().lower()
    return name if name in VALID_STATES else "idle"


def broadcast(name: str) -> None:
    """Estado: canal confiable (cola por cliente)."""
    with _lock:
        _state["name"] = name
        clients = list(_clients)
    _touch()
    for q in clients:
        try:
            q.put_nowait(name)
        except queue.Full:
            pass


def _watchdog() -> None:
    """Si voice_claude muere a mitad, no dejar el orbe clavado: vuelve a idle."""
    while True:
        time.sleep(10)
        with _lock:
            stuck = _state["name"] != "idle"
            idle_for = time.monotonic() - _last_activity
        if stuck and idle_for > IDLE_TIMEOUT:
            broadcast("idle")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_a):  # silencioso
        pass

    def _authorized(self) -> bool:
        if not TOKEN:
            return True
        qs = parse_qs(urlparse(self.path).query)
        return (qs.get("token") or [""])[0] == TOKEN

    def _send_bytes(self, data: bytes, ctype: str, code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            try:
                self._send_bytes(HTML.read_bytes(), "text/html; charset=utf-8")
            except OSError:
                self.send_error(500, "orb.html missing")
            return
        if path.startswith("/vendor/"):
            return self._serve_vendor(path)
        if path == "/healthz":
            self._send_bytes(b"ok", "text/plain")
            return
        if path == "/events":
            return self._serve_events()
        self.send_error(404)

    def _serve_vendor(self, path: str):
        target = (HERE / path.lstrip("/")).resolve()
        if not str(target).startswith(str(VENDOR)) or not target.is_file():
            self.send_error(404)
            return
        ctype = MIME.get(target.suffix, "application/octet-stream")
        try:
            self._send_bytes(target.read_bytes(), ctype)
        except OSError:
            self.send_error(404)

    def _serve_events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        q: queue.Queue = queue.Queue(maxsize=64)
        with _lock:
            _clients.add(q)
            cur = _state["name"]
        last_ping = time.monotonic()
        try:
            self.wfile.write(f"data: {cur}\n\n".encode())
            self.wfile.flush()
            while True:
                try:
                    name = q.get(timeout=1.0)         # solo estados (poco frecuentes); ping cada 15s
                    self.wfile.write(f"data: {name}\n\n".encode())
                    self.wfile.flush()
                except queue.Empty:
                    now = time.monotonic()
                    if now - last_ping > 15:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                        last_ping = now
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with _lock:
                _clients.discard(q)

    def do_POST(self):
        parsed = urlparse(self.path)
        if not self._authorized():
            self.send_error(403)
            return
        ln = int(self.headers.get("Content-Length") or 0)
        if ln:
            self.rfile.read(ln)                       # drena el body
        if parsed.path == "/state":
            name = (parse_qs(parsed.query).get("s") or [None])[0]
            broadcast(normalize_state(name))
            self._ok204()
            return
        self.send_error(404)

    def _ok204(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()


def main() -> None:
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:
        # puerto tomado -> ya hay otra instancia corriendo
        sys.exit(0)
    server.daemon_threads = True
    threading.Thread(target=_watchdog, daemon=True).start()
    server.serve_forever()


if __name__ == "__main__":
    main()
