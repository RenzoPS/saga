"""Orquestación: el toggle Win+Z entra acá. Decide stop/abort/start y corre el
flujo grabar -> transcribir -> Claude -> hablar, con el orbe siguiendo la fase."""

import os
import sys
import signal
from pathlib import Path

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


def start_path() -> int:
    ensure_orb()
    ensure_monitor_open()
    prewarm_whisper()  # modelo Whisper carga en paralelo mientras el usuario graba
    prewarm_claude()   # daemon Claude calienta plugins/sesión en paralelo (sin cold-start)
    LOCK_FILE.write_text(self_identity())   # pid:starttime -> anti PID-recycle
    ABORT_FILE.unlink(missing_ok=True)      # owner nuevo -> resetear tracker de zombie
    signal.signal(signal.SIGUSR2, cancel_handler)

    try:
        try:
            duration = record_until_signaled()
        finally:
            PID_FILE.unlink(missing_ok=True)

        if _cancel.is_set():
            log("cancel after rec")
            orb_state("cancel")
            return 0

        if duration < MIN_DURATION_S:
            orb_state("error")
            return 0

        orb_state("transcribe")
        text = transcribe()

        if _cancel.is_set():
            log("cancel after transcribe")
            orb_state("cancel")
            return 0

        if not text:
            orb_state("error")
            return 0

        if is_reset_command(text):
            reset_claude()   # resetea sesión + respawnea el daemon (o resetea el archivo si no hay daemon)
            log("reset by voice keyword")
            orb_state("nueva")
            return 0

        # Captura screenshot SOLO si el prompt referencia algo visual.
        attach_screenshot: "Path | None" = None
        if is_visual_command(text):
            log("visual keyword detected, capturing screenshot")
            attach_screenshot = take_screenshot()
            if attach_screenshot is not None:
                orb_state("screen")
            else:
                orb_state("think")
        else:
            orb_state("think")

        streamer = TTSStreamer()
        set_current_streamer(streamer)

        spoke = [False]   # ¿Claude produjo algún token? (para detectar fallo/sesión muerta)

        def on_first_token() -> None:
            spoke[0] = True
            orb_state("speak")

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

        if _cancel.is_set():
            log("cancel during streaming")
            orb_state("cancel")
            return 0

        if not spoke[0]:
            # Claude no produjo respuesta: binario ausente, sesión cerrada, crash...
            # Feedback visible en vez de quedar mudo (orbe a 'error' amarillo).
            log("claude no produjo respuesta -> error")
            orb_state("error")
            return 0

        orb_state("idle")
        return 0
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
