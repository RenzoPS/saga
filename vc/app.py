"""Orquestación: el toggle Win+Z entra acá. Decide stop/abort/start y corre el
flujo grabar -> transcribir -> Claude -> hablar, con el orbe siguiendo la fase."""

import os
import sys
import signal
from pathlib import Path

import os

from .config import LOCK_FILE, PID_FILE, ABORT_FILE, MIN_DURATION_S, PROJECT_DIR
from .runtime import (
    log,
    _cancel,
    cancel_handler,
    set_current_streamer,
    read_recorder_pid,
    read_owner_pid,
    self_identity,
    signal_stop,
    signal_cancel,
)
from .orb import ensure_orb, orb_state
from .desktop import ensure_monitor_open, take_screenshot
from .audio import record_until_signaled
from .stt import prewarm_whisper, transcribe
from .session import is_reset_command, is_visual_command
from .tts import TTSStreamer, load_word_aliases, stream_to_sentences
from .claudecli import ask_claude_stream, prewarm_claude, reset_claude

# Modo wake (estilo Alexa): lo activa el wake_daemon vía env (mismo flag que el
# auto-stop por silencio en audio.py). UN turno por "claude": graba, responde, y
# vuelve a idle esperando el próximo "claude". No es conversacional/multi-turno.
WAKE_MODE = os.environ.get("VOICE_WAKE_AUTOSTOP") == "1"


def stop_path() -> int:
    pid = read_recorder_pid()
    if pid is None:
        log("stop called but no live recorder")
        return 1
    log(f"signaling recorder pid={pid}")
    signal_stop(pid)
    return 0


def _read_abort_ident() -> "str | None":
    try:
        return ABORT_FILE.read_text().strip()
    except OSError:
        return None


def abort_path() -> int:
    pid = read_owner_pid()   # valida vivo + starttime (un PID reciclado no pasa)
    if pid is None:
        log("abort called but no owner")
        return 1
    try:
        ident = LOCK_FILE.read_text().strip()   # "pid:starttime" del dueño actual
    except OSError:
        ident = ""

    # Lock auto-sanable: si a ESTE MISMO owner (misma identidad pid:starttime) ya lo
    # abortamos y sigue vivo, está colgado (zombie). Lo matamos y tomamos el control.
    if ident and _read_abort_ident() == ident:
        log(f"owner {ident} no murió tras abort -> ZOMBIE, SIGKILL + reclaim")
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        LOCK_FILE.unlink(missing_ok=True)
        PID_FILE.unlink(missing_ok=True)
        ABORT_FILE.unlink(missing_ok=True)
        return start_path()

    # Cancel normal (interrumpir una respuesta en curso). Instantáneo.
    log(f"signaling abort to owner pid={pid}")
    signal_cancel(pid)
    try:
        ABORT_FILE.write_text(ident or str(pid))   # identidad del owner (detección de zombie)
    except OSError:
        pass
    orb_state("cancel")
    return 0


def _do_turn() -> str:
    """Un turno: grabar -> transcribir -> Claude -> hablar. Devuelve el estado:
      'cancel' (Win+Z cortó) · 'short' (muy corto) · 'empty' (sin texto) ·
      'reset' (keyword reset) · 'error' (Claude mudo) · 'ok'.
    En modo wake el beep ya lo tocó el wake_daemon al oír 'claude'."""
    try:
        duration = record_until_signaled()
    finally:
        PID_FILE.unlink(missing_ok=True)

    if _cancel.is_set():
        return "cancel"
    if duration < MIN_DURATION_S:
        return "short"

    orb_state("transcribe")
    text = transcribe()

    if _cancel.is_set():
        return "cancel"
    if not text:
        return "empty"
    if is_reset_command(text):
        reset_claude()   # resetea sesión + respawnea el daemon
        log("reset by voice keyword")
        return "reset"

    # Captura screenshot SOLO si el prompt referencia algo visual.
    attach_screenshot: "Path | None" = None
    if is_visual_command(text):
        log("visual keyword detected, capturing screenshot")
        attach_screenshot = take_screenshot()
        orb_state("screen" if attach_screenshot is not None else "think")
    else:
        orb_state("think")

    spoke = [False]   # ¿Claude produjo algún token? (para detectar fallo/sesión muerta)

    def on_first_token() -> None:
        spoke[0] = True   # llegó token: el orbe SIGUE en 'think' (puede estar usando tools)

    # 'speak' recién cuando sale el primer audio real por el parlante (no en el 1er token).
    streamer = TTSStreamer(on_play_start=lambda: orb_state("speak"))
    set_current_streamer(streamer)

    try:
        stream_to_sentences(
            ask_claude_stream(
                text,
                on_first_token=on_first_token,
                screenshot_path=attach_screenshot,
            ),
            streamer,
        )
    finally:
        streamer.finish()
        streamer.wait(timeout=120)
        set_current_streamer(None)
        if attach_screenshot is not None:
            attach_screenshot.unlink(missing_ok=True)   # borrar captura (puede tener secretos en pantalla)

    if _cancel.is_set():
        return "cancel"
    if not spoke[0]:
        return "error"   # Claude no produjo respuesta (binario ausente, sesión muerta, crash)
    return "ok"


def _single_turn() -> int:
    """Un solo turno (Win+Z clásico y modo wake estilo Alexa). Tras responder,
    vuelve a idle. 'gracias' va a Claude como cualquier consulta (sin despedidas)."""
    status = _do_turn()
    orb_state({
        "cancel": "cancel",
        "short": "error",
        "empty": "error",
        "reset": "nueva",
        "error": "error",
    }.get(status, "idle"))
    return 0


def start_path() -> int:
    ensure_orb()
    ensure_monitor_open()
    prewarm_whisper()  # modelo Whisper carga en paralelo mientras el usuario graba
    prewarm_claude()   # daemon Claude calienta plugins/sesión en paralelo (sin cold-start)
    if WAKE_MODE:
        ww = os.environ.get("VOICE_WAKE_WORD", "").strip()
        log(f"=== despertado por: '{ww or '?'}' -> un turno (modo Alexa) ===")
    LOCK_FILE.write_text(self_identity())   # pid:starttime -> anti PID-recycle
    ABORT_FILE.unlink(missing_ok=True)      # owner nuevo -> resetear tracker de zombie
    signal.signal(signal.SIGUSR2, cancel_handler)

    try:
        return _single_turn()
    finally:
        LOCK_FILE.unlink(missing_ok=True)


def main() -> int:
    if "--doctor" in sys.argv:
        from .doctor import doctor
        return doctor()

    PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    load_word_aliases()

    recorder_pid = read_recorder_pid()
    if recorder_pid is not None:
        return stop_path()

    owner_pid = read_owner_pid()
    if owner_pid is not None:
        log(f"busy: owner pid={owner_pid} -> abort")
        return abort_path()

    return start_path()
