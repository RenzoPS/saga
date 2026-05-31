"""Transcripción (STT). Cliente del daemon Whisper caliente; si el daemon no
está disponible, fallback que carga el modelo inline (lento pero robusto)."""

import os
import sys
import json
import socket
import time
import subprocess

from .config import (
    WHISPER_SOCK,
    WHISPER_DAEMON,
    WHISPER_SIZE,
    WHISPER_BEAM,
    WHISPER_IDLE_S,
    AUDIO_FILE,
)
from .runtime import log, _cancel


def _whisper_daemon_up() -> bool:
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.3)
        s.connect(str(WHISPER_SOCK))
        s.close()
        return True
    except OSError:
        return False


def prewarm_whisper() -> None:
    """Spawnea el daemon de Whisper si no corre. NO bloquea: el modelo carga en
    paralelo mientras el usuario graba, asi transcribe() no paga la recarga."""
    if _whisper_daemon_up():
        return
    try:
        subprocess.Popen(
            [sys.executable, str(WHISPER_DAEMON)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env={
                **os.environ,
                "VOICE_WHISPER_SOCK": str(WHISPER_SOCK),
                "VOICE_WHISPER_SIZE": WHISPER_SIZE,
                "VOICE_WHISPER_BEAM": str(WHISPER_BEAM),
                "VOICE_WHISPER_IDLE": str(WHISPER_IDLE_S),
            },
        )
        log("whisper daemon spawned (prewarm)")
    except OSError as e:
        log(f"whisper daemon spawn fail: {e}")


def _transcribe_via_daemon(ready_timeout: float = 10.0, recv_timeout: float = 60.0) -> "str | None":
    """Pide la transcripcion al daemon. Devuelve texto, o None si no se pudo
    (para caer al fallback inline).

    Dos timeouts separados (clave): `ready_timeout` acota cuánto esperamos a que el
    daemon acepte conexión (está cargando o murió) -> si murió, caemos a inline en
    ~10s, no 90s. `recv_timeout` acota la transcripción en sí (beam=5 tarda ~6-8s),
    que debe ser largo para no cortar una transcripción legítima."""
    deadline = time.monotonic() + ready_timeout
    conn = None
    while time.monotonic() < deadline:
        if _cancel.is_set():
            return None
        try:
            conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            conn.settimeout(2.0)   # cada intento de conexión es corto
            conn.connect(str(WHISPER_SOCK))
            break
        except OSError:
            conn = None
            time.sleep(0.15)
    if conn is None:
        return None
    try:
        conn.settimeout(recv_timeout)   # la transcripción puede tardar varios segundos
        conn.sendall((json.dumps({"audio": str(AUDIO_FILE), "lang": "es"}) + "\n").encode())
        buf = b""
        while b"\n" not in buf:
            chunk = conn.recv(4096)
            if not chunk:
                break
            buf += chunk
        if not buf:
            return None
        resp = json.loads(buf.split(b"\n", 1)[0].decode())
        if not resp.get("ok"):
            log(f"whisper daemon error: {resp.get('error')}")
            return None
        return resp.get("text", "")
    except Exception as e:
        log(f"whisper daemon req fail: {type(e).__name__}: {e}")
        return None
    finally:
        try:
            conn.close()
        except OSError:
            pass


def _transcribe_inline() -> str:
    """Fallback: carga el modelo en este proceso (lento, paga ~3s) si el daemon
    no esta disponible. Garantiza que el voice-assistant nunca quede mudo."""
    log("whisper fallback inline (carga modelo)")
    from faster_whisper import WhisperModel

    model = WhisperModel(
        WHISPER_SIZE,
        device="cpu",
        compute_type="int8",
        cpu_threads=4,  # 4 cores fisicos del Ryzen 5 3450U, SMT no ayuda en ML int8
    )
    segments, _info = model.transcribe(
        str(AUDIO_FILE),
        language="es",
        beam_size=WHISPER_BEAM,
        vad_filter=True,
        condition_on_previous_text=False,
        temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],  # fallback: reintenta si sale repetitivo/baja confianza
        compression_ratio_threshold=2.4,
        log_prob_threshold=-1.0,
        no_speech_threshold=0.6,
        no_repeat_ngram_size=3,  # prohíbe repetir trigramas -> mata loops "a ir a ir a ir"
    )
    return " ".join(s.text.strip() for s in segments).strip()


def transcribe() -> str:
    log("whisper transcribe (daemon)")
    text = _transcribe_via_daemon()
    if text is None:
        text = _transcribe_inline()
    log(f"whisper out: {text!r}")
    return text
