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

from .config import ORB_URL, ORB_PORT, ORB_SERVER
from .runtime import log


def _orb_up() -> bool:
    try:
        urllib.request.urlopen(ORB_URL + "healthz", timeout=0.4)
        return True
    except Exception:
        return False


def ensure_orb() -> None:
    """Levanta el server del orbe si no corre y abre la pestaña esa primera vez."""
    if _orb_up():
        return
    try:
        subprocess.Popen(
            [sys.executable, str(ORB_SERVER)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env={**os.environ, "ORB_PORT": str(ORB_PORT)},
        )
    except OSError as e:
        log(f"orb spawn fail: {e}")
        return
    for _ in range(25):
        if _orb_up():
            break
        time.sleep(0.1)
    # server recien levantado -> abrir pestaña una vez
    try:
        subprocess.Popen(
            ["xdg-open", ORB_URL],
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
        for attempt in (1, 2):
            try:
                if self._conn is None:
                    self._conn = http.client.HTTPConnection("127.0.0.1", ORB_PORT, timeout=0.5)
                self._conn.request("POST", path, body=b"")
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
