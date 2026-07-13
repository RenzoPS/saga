"""Cliente del orbe visual: levanta el server SSE si hace falta y le manda el
ESTADO por HTTP de forma no bloqueante (~5 posts/conversación). El nivel de audio
ya no se manda (el orbe anima stylized)."""

import os
import sys
import queue
import threading
import time
import http.client
import urllib.request
import subprocess

from .config import ORB_URL, ORB_PORT, ORB_SERVER, orb_token
from .runtime import log


def orb_url_with_token() -> str:
    """URL de bootstrap del orbe. El token viaja UNA vez por la URL (el browser no tiene otra via
    de arranque); la pagina lo guarda en memoria y lo saca de la barra con history.replaceState."""
    return f"{ORB_URL}?token={orb_token()}"


def _orb_up() -> bool:
    # /healthz es la UNICA ruta exenta de token (U2): es el probe de readiness, no expone nada.
    try:
        urllib.request.urlopen(ORB_URL + "healthz", timeout=0.4)
        return True
    except Exception:
        return False


def ensure_orb(open_browser: bool = True) -> None:
    """Levanta el server del orbe si no corre y abre la pestaña esa primera vez.

    open_browser=False: solo asegura el server, NO abre el browser. Lo usa el modo room
    (_start_room) que abre la pestaña él mismo DESPUÉS del dispatch -> evita la doble pestaña."""
    if _orb_up():
        return
    try:
        subprocess.Popen(
            [sys.executable, str(ORB_SERVER)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            # ORB_TOKEN (U2): el server lo toma del env; si no viniera, lo leeria del mismo archivo
            # de runtime (vc.config.orb_token) -> mismo token igual. Lo pasamos explicito por claridad.
            env={**os.environ, "ORB_PORT": str(ORB_PORT), "ORB_TOKEN": orb_token()},
        )
    except OSError as e:
        log(f"orb spawn fail: {e}")
        return
    for _ in range(25):
        if _orb_up():
            break
        time.sleep(0.1)
    if not open_browser:
        return
    # server recien levantado -> abrir pestaña una vez
    try:
        subprocess.Popen(
            ["xdg-open", orb_url_with_token()],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as e:
        log(f"xdg-open fail: {e}")


class _OrbClient:
    """Sender persistente y NO bloqueante hacia el orbe.

    - Estados por cola confiable (no se pierden).
    - Una sola conexion HTTP keep-alive; los callers nunca bloquean en red.
    """

    def __init__(self) -> None:
        self._q: queue.Queue = queue.Queue(maxsize=64)
        self._lock = threading.Lock()
        self._conn: "http.client.HTTPConnection | None" = None
        self._started = False
        self._post_ok = True   # estado de salud del POST (para loguear solo en transiciones)

    def _ensure_thread(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        threading.Thread(target=self._loop, daemon=True).start()

    def state(self, name: str) -> None:
        self._ensure_thread()
        try:
            self._q.put_nowait(name)
        except queue.Full:
            pass

    def _post(self, path: str) -> None:
        # U2: el server exige token en TODO endpoint. Este POST corre DENTRO del worker (otro proceso),
        # asi que el token sale del archivo de runtime (fuente unica). Sin el header -> 401 y el orbe
        # se quedaria clavado en idle.
        headers = {"X-Orb-Token": orb_token()}
        for attempt in (1, 2):
            try:
                if self._conn is None:
                    self._conn = http.client.HTTPConnection("127.0.0.1", ORB_PORT, timeout=0.5)
                self._conn.request("POST", path, body=b"", headers=headers)
                self._conn.getresponse().read()
                if not self._post_ok:
                    log("orb reconectado (POST OK de nuevo)")
                    self._post_ok = True
                return
            except Exception as e:
                try:
                    if self._conn:
                        self._conn.close()
                except Exception:
                    pass
                self._conn = None  # reconecta en el proximo intento
                if attempt == 2 and self._post_ok:   # log SOLO en la transicion ok->fail (sin spam)
                    log(f"orb POST fail ({path.split('?')[0]}): {type(e).__name__} — server caido?")
                    self._post_ok = False

    def _loop(self) -> None:
        # Solo estados (un puñado por conversación). Sin nivel de audio -> sin flood HTTP.
        while True:
            name = self._q.get()
            self._post(f"/state?s={name}")


_orb = _OrbClient()


def orb_state(name: str) -> None:
    _orb.state(name)
