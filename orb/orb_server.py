#!/usr/bin/env python3
"""Server persistente del orbe de saga.

Sirve orb.html (+ vendor local de three.js) en localhost y emite por SSE el
estado actual (canal confiable, no se pierde). saga.py hace POST /state?s=<fase>.
(El nivel de audio se removió: el orbe anima stylized, no recibe audio.)
Endpoints de entrada del panel del orbe (reenvian al socket o escriben /tmp, sin tocar el stack de voz):
  POST /attach?kind=image  -> imagen pegada -> dead-drop en /tmp (binaria, Claude la lee de disco).
  POST /stage              -> texto del textarea (autosave) -> reenvia `stage <b64>` al socket de
                              control del agente, que lo guarda en MEMORIA (no toca el filesystem).
  POST /say                -> prompt directo (Shift+Enter) -> reenvia `say <b64>` al socket -> el
                              agente dispara un turno inmediato sin grabar voz.
  GET  /token              -> (modo room, Ciclo 4) emite el JWT con el que el cliente browser se
                              une al room de livekit-server. Mintea con livekit.api (import lazy;
                              el resto del módulo sigue stdlib-only).
Stdlib + paths/constantes de vc.config. La única dep pip es livekit-api, y SOLO se importa
dentro de /token (lazy) -> el orbe en modo console no la necesita.

Estados: idle, rec, transcribe, screen, think, speak, nueva, error, cancel, attach.
"""
import os
import sys
import json
import time
import queue
import base64
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# Paths del adjunto: fuente unica en vc.config. Insertamos el root del repo en sys.path
# (mismo patron que los daemons del proyecto) para importar la constante sin duplicar la ruta.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from vc.config import (
    ATTACH_IMG_PATH, LK_CTL_SOCK,
    LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, LIVEKIT_ROOM, LIVEKIT_AGENT_NAME,
)

PORT = int(os.environ.get("ORB_PORT", "8777"))
TOKEN = os.environ.get("ORB_TOKEN", "")          # vacio = sin auth (local)
# Wake (U4): el cliente lee este flag del /token para decidir si publica el mic DESMUTEADO siempre
# (wake ON: el server necesita oír "hey saga") o gateado por estado (wake OFF, default). OJO:
# bool("0") es True -> comparar el valor real, no bool() sobre el env crudo.
WAKE_ENABLED = os.environ.get("SAGA_WAKE_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")
IDLE_TIMEOUT = 180.0                              # seg sin actividad -> vuelve a idle
HERE = Path(__file__).resolve().parent
HTML = HERE / "orb.html"
VENDOR = (HERE / "vendor").resolve()

VALID_STATES = {
    "idle", "rec", "transcribe", "screen",
    "think", "speak", "nueva", "error", "cancel", "attach",
}
MIME = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
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
    """Si saga muere a mitad, no dejar el orbe clavado: vuelve a idle."""
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
        if path == "/token":
            return self._serve_token()
        if path == "/events":
            return self._serve_events()
        self.send_error(404)

    def _serve_token(self):
        """Emite el JWT del cliente para unirse al room. GET /token?identity=&room=.
        Mintea con livekit.api (import lazy: el orbe en modo console nunca pega acá).
        Respuesta: {"url": "ws://127.0.0.1:7880", "token": "<jwt>", "room": "saga", "wake": <bool>}.
        `wake` (U4): si true, el cliente publica el mic DESMUTEADO siempre (el server oye "hey saga")."""
        if not LIVEKIT_API_KEY or not LIVEKIT_API_SECRET:
            self.send_error(500, "LIVEKIT_API_KEY/SECRET sin configurar (.env.local)")
            return
        qs = parse_qs(urlparse(self.path).query)
        identity = (qs.get("identity") or ["saga-client"])[0]
        room = (qs.get("room") or [LIVEKIT_ROOM])[0]
        try:
            from livekit import api  # lazy: única dep pip del módulo
            token = (
                api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
                .with_identity(identity)
                .with_grants(api.VideoGrants(room_join=True, room=room))
                # Dispatch EXPLÍCITO: el server despacha al agente nombrado cuando este cliente
                # crea/entra al room -> no depende de que el worker esté listo antes (auto-dispatch).
                .with_room_config(api.RoomConfiguration(
                    agents=[api.RoomAgentDispatch(agent_name=LIVEKIT_AGENT_NAME)]
                ))
                .to_jwt()
            )
        except Exception as e:  # noqa: BLE001 - degradar a 500 con causa
            self.send_error(500, f"no se pudo emitir el token: {e}")
            return
        body = json.dumps(
            {"url": LIVEKIT_URL, "token": token, "room": room, "wake": WAKE_ENABLED}
        ).encode()
        self._send_bytes(body, "application/json")

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
        body = self.rfile.read(ln) if ln else b""     # leemos el body (lo usa /attach)
        if parsed.path == "/state":
            name = (parse_qs(parsed.query).get("s") or [None])[0]
            broadcast(normalize_state(name))
            self._ok204()
            return
        if parsed.path == "/attach":
            kind = (parse_qs(parsed.query).get("kind") or [""])[0]
            self._stage_image(kind, body)
            return
        if parsed.path == "/stage":
            # Autosave del textarea: SIEMPRE reenvía (body vacío -> el agente limpia el staged).
            self._forward_ctl("stage", body, allow_empty=True)
            return
        if parsed.path == "/say":
            # Shift+Enter: no disparar un turno vacío.
            if not body.strip():
                self._ok204()
                return
            self._forward_ctl("say", body, allow_empty=False)
            return
        self.send_error(404)

    def _forward_ctl(self, verb: str, body: bytes, allow_empty: bool) -> None:
        """Reenvía `verb <b64>` al socket de control del agente LiveKit. El payload va en base64
        en una sola línea (tolera saltos de línea sin romper el framing por readline). NO toca el
        stack de voz: solo le pasa un comando al agente, que decide qué hacer."""
        if not body.strip() and not allow_empty:
            self._ok204()
            return
        try:
            payload = base64.b64encode(body).decode("ascii")   # body vacío -> payload ""
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(2.0)
            s.connect(str(LK_CTL_SOCK))
            s.sendall(verb.encode("ascii") + b" " + payload.encode("ascii") + b"\n")
            s.recv(64)
            s.close()
        except OSError:
            self.send_error(503, "agente LiveKit no responde")
            return
        self._ok204()

    def _stage_image(self, kind: str, body: bytes) -> None:
        """Imagen pegada -> dead-drop en /tmp (binaria; Claude la lee como screenshot_path). El
        navegador manda el contenido completo -> OVERWRITE; body vacío -> BORRA. /tmp es tmpfs."""
        if kind != "image":
            self.send_error(400, "kind invalido (solo image; el texto va por /stage)")
            return
        try:
            if body:
                ATTACH_IMG_PATH.write_bytes(body)
                os.chmod(ATTACH_IMG_PATH, 0o600)
            else:
                ATTACH_IMG_PATH.unlink(missing_ok=True)
        except OSError:
            self.send_error(500, "no se pudo guardar el adjunto")
            return
        self._ok204()

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
