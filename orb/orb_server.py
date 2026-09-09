#!/usr/bin/env python3
"""Server persistente del orbe de saga.

Sirve orb.html (+ vendor local de three.js) en localhost y emite por SSE el
estado actual (canal confiable, no se pierde). El agente hace POST /state?s=<fase> (vc/orb.orb_state).
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
dentro de /token (lazy) -> el resto del módulo es stdlib puro.

Estados: idle, rec, listen, transcribe, screen, think, speak, nueva, error, cancel, attach.
('listen' = modo llamada: linea abierta esperandote, distinto del 'rec' puntual de push-to-talk.)
"""
import os
import sys
import json
import time
import hmac
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
    ATTACH_IMG_PATH, LK_CTL_SOCK, orb_token,
    LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, LIVEKIT_ROOM,
)
from vc.dispatch import ensure_agent

PORT = int(os.environ.get("ORB_PORT", "8777"))
# U2/FR3.1: el token NO puede quedar vacio. Antes: `os.environ.get("ORB_TOKEN", "")` + `if not TOKEN:
# return True` = CERO auth (agujero S5, el mismo patron del CVE-2024-28224 de Ollama). Ahora: si el
# env no lo trae, lo tomamos del archivo de runtime (vc.config.orb_token, fuente unica de los 3 procesos).
TOKEN = os.environ.get("ORB_TOKEN", "").strip() or orb_token()

# U2/FR3.7 — anti-DNS-rebinding: allowlist EXACTA del header Host. Bajo rebinding el atacante es
# same-origin (el browser le manda el token igual), asi que ninguna otra capa lo detecta: este check
# es LA defensa. Match exacto y nada de substrings: `"127.0.0.1" in host` deja pasar 127.0.0.1.evil.com.
# El puerto permitido es el REAL al que el server esta atado (self.server.server_address), no el del
# env: asi el check es correcto en produccion (8777) y en un server de test bindeado a un puerto libre.
_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]")


def _allowed_hosts(port: int) -> frozenset:
    return frozenset(f"{h}:{port}" for h in _LOOPBACK_HOSTS)

# U2/FR3.4 — tope de body por ruta. /attach escribe a /tmp, que es tmpfs = RAM: sin cap, un body de
# varios GB te come la RAM. El limite se chequea ANTES de leer (413 sin tocar RAM ni disco).
MAX_BODY = 8 * 1024                                # default de los POST
LIMITS = {"/attach": 10 * 1024 * 1024,             # imagen: un PNG full-HD ronda 1-3 MB
          "/say": 64 * 1024, "/stage": 64 * 1024}  # texto: 64 KB ~ 10.000 palabras

# U2/FR3.3 — headers de seguridad. La CSP es deliberadamente ACOTADA: NO toca script-src ni
# connect-src (restringirlos obligaria a enumerar el WS de LiveKit y romperia el WebRTC -> saga muda).
# form-action 'none' es el que mas compra: mata el POST por <form>, el unico CSRF que el header
# custom no puede frenar (un <form> no setea headers, pero tampoco dispara preflight -> llegaria igual).
SECURITY_HEADERS = (
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),            # que el ?token= no se filtre por el Referer
    ("Content-Security-Policy", "frame-ancestors 'none'; form-action 'none'; base-uri 'none'"),
)
JWT_TTL = 300.0                                    # 5 min: solo tiene que cubrir el JOIN (ver _serve_token)
# Wake (U4): el cliente lee este flag del /token para decidir si publica el mic DESMUTEADO siempre
# (wake ON: el server necesita oír "hey saga") o gateado por estado (wake OFF, default). OJO:
# bool("0") es True -> comparar el valor real, no bool() sobre el env crudo.
WAKE_ENABLED = os.environ.get("SAGA_WAKE_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")
IDLE_TIMEOUT = 180.0                              # seg sin actividad -> vuelve a idle
HERE = Path(__file__).resolve().parent
HTML = HERE / "orb.html"
VENDOR = (HERE / "vendor").resolve()

VALID_STATES = {
    "idle", "rec", "listen", "transcribe", "screen",
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
        """Token valido? Header X-Orb-Token (los fetch) o ?token= (bootstrap y SSE).

        El query param NO es una eleccion de diseño: EventSource NO acepta headers custom (limitacion
        del browser), asi que /events no tiene otra via. compare_digest = comparacion en tiempo
        constante (`==` corta en el primer byte distinto -> timing leak)."""
        sent = self.headers.get("X-Orb-Token")
        if not sent:
            sent = (parse_qs(urlparse(self.path).query).get("token") or [""])[0]
        # compare_digest tira TypeError con strings no-ASCII -> lo tratamos como token invalido
        # (fail-closed): un token real es token_urlsafe (ASCII), asi que no-ASCII nunca es legitimo.
        try:
            return hmac.compare_digest(sent, TOKEN)
        except TypeError:
            return False

    def _gate(self) -> bool:
        """Puerta UNICA: corre antes de CUALQUIER handler, en GET y en POST. Fail-closed.

        Antes, `_authorized()` se llamaba SOLO en do_POST -> /token (que mintea el JWT) y /events
        quedaban abiertos incluso con token configurado. Una auth opt-in por ruta garantiza que el
        proximo endpoint nazca inseguro; por eso la validacion vive en un solo lugar.

        Orden (importa): Host -> healthz -> token -> tamaño. El Host va PRIMERO porque bajo DNS
        rebinding el atacante es same-origin y trae el token: ninguna capa posterior lo detectaria.
        Devuelve True si el request puede seguir; si devuelve False, ya respondio el error.
        """
        addr = self.server.server_address                      # (host, port) en TCP
        bound_port = addr[1] if isinstance(addr, tuple) else PORT
        if self.headers.get("Host") not in _allowed_hosts(bound_port):   # FR3.7 (match exacto)
            self.send_error(403, "host no permitido")
            return False
        path = urlparse(self.path).path
        # Exentas del token (NO del Host check, que ya paso): /healthz (probe de readiness) y /vendor/*
        # (three.js + SDK de LiveKit, assets estaticos SIN secretos). Los assets se cargan por <script
        # src>/import de ES modules, que NO pueden mandar el header X-Orb-Token -> exigirlo dejaba la
        # pagina sin three.js (WebGL muerto). El path traversal de /vendor ya esta bloqueado aparte.
        if path == "/healthz" or path.startswith("/vendor/"):
            return True
        if not self._authorized():                             # FR3.1 (deny by default)
            self.send_error(401, "token invalido o ausente")
            return False
        if self.command == "POST":                             # FR3.4 (limite ANTES de leer el body)
            if int(self.headers.get("Content-Length") or 0) > LIMITS.get(path, MAX_BODY):
                self.send_error(413, "body demasiado grande")
                return False
        return True

    def _send_bytes(self, data: bytes, ctype: str, code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in SECURITY_HEADERS:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self._gate():
            return
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
        """Emite el JWT del cliente para unirse al room. GET /token.
        Mintea con livekit.api (import lazy: solo /token la necesita).
        Respuesta: {"url": "ws://127.0.0.1:7880", "token": "<jwt>", "room": "saga", "wake": <bool>}.
        `wake` (U4): si true, el cliente publica el mic DESMUTEADO siempre (el server oye "hey saga").

        U2/FR3.6: `identity` y `room` los fija el SERVER. Antes salian del QUERY del cliente y se
        FIRMABAN en el JWT -> el cliente elegia en que room entrar y con que identidad (S8).

        U2/FR3.5: TTL explicito (5 min) + grants minimos. El default del SDK son 6h y grants abiertos.
        El TTL corto es seguro: la doc oficial de LiveKit dice que "expiration time only impacts the
        initial connection, and not subsequent reconnects" (el server empuja tokens refrescados por el
        signal channel) -> un TTL corto NO rompe reconexiones. Y como el self-hosted NO tiene revocacion
        (es Cloud-only), el TTL corto es la UNICA red si el JWT se filtra.
        """
        if not LIVEKIT_API_KEY or not LIVEKIT_API_SECRET:
            self.send_error(500, "LIVEKIT_API_KEY/SECRET sin configurar (.env.local)")
            return
        try:
            from datetime import timedelta
            from livekit import api  # lazy: única dep pip del módulo
            token = (
                api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
                .with_identity("saga-client")            # del SERVER, no del query (FR3.6)
                .with_ttl(timedelta(seconds=JWT_TTL))    # FR3.5: 5 min (default del SDK: 6h)
                .with_grants(api.VideoGrants(
                    room_join=True,
                    room=LIVEKIT_ROOM,                   # del SERVER, no del query (FR3.6)
                    can_subscribe=True,                  # escucha el track TTS del worker
                    can_publish=True,
                    can_publish_sources=["microphone"],  # SOLO el mic: ni camara ni screenshare
                    can_publish_data=False,
                    can_update_own_metadata=False,
                ))
                # El token es SOLO para unirse al room. El dispatch del agente NO va acá:
                # `RoomConfiguration.agents` pide un job `JT_PARTICIPANT` y el SDK de Python sólo
                # registra workers `JT_ROOM`/`JT_PUBLISHER` -> el server responde "not dispatching
                # agent job since no worker is available". Se pide por API en `vc.dispatch`,
                # justo abajo. Ver el módulo para el detalle.
                .to_jwt()
            )
        except Exception as e:  # noqa: BLE001 - degradar a 500 con causa
            self.send_error(500, f"no se pudo emitir el token: {e}")
            return
        # El cliente está por entrar al room: es EL momento de pedir el agente. Acá el orden de
        # arranque deja de importar (el bug era justamente que el room nacía antes que el worker).
        # Idempotente y fail-soft: si el agente ya está, no hace nada; si LiveKit no contesta,
        # el token igual sale. Ver vc/dispatch.py.
        ensure_agent()
        body = json.dumps(
            {"url": LIVEKIT_URL, "token": token, "room": LIVEKIT_ROOM, "wake": WAKE_ENABLED}
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
        # U2/FR3.2: se fue el `Access-Control-Allow-Origin: *`. Mandarlo INVITABA a cualquier pagina
        # abierta a leer el estado de saga en vivo. Sin headers CORS, el browser no deja leer la
        # respuesta cross-origin, y el preflight que fuerza X-Orb-Token pasa a ser una defensa real.
        # El token de /events viaja por ?token= (el SSE no acepta headers custom) y ya lo valido _gate().
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        for k, v in SECURITY_HEADERS:
            self.send_header(k, v)
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
        if not self._gate():          # host + token + LIMITE DE TAMAÑO, antes de leer un solo byte
            return
        parsed = urlparse(self.path)
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
        for k, v in SECURITY_HEADERS:   # U2/FR3.2: se fue el `Access-Control-Allow-Origin: *`
            self.send_header(k, v)
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
