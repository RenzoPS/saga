"""Estado runtime + control de procesos: log, evento de cancelación, registros
de proceso/streamer actuales, signal handlers y helpers de PID-file.

Centraliza el estado mutable compartido para que el resto de los módulos no
dependan entre sí (evita ciclos de import)."""

import os
import signal
import subprocess
import threading
import time

from .config import LOG_FILE

_LOG_MAX = 512 * 1024  # 512KB -> rota a .old (evita crecimiento infinito)


def _rotate_log() -> None:
    try:
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > _LOG_MAX:
            LOG_FILE.replace(LOG_FILE.with_suffix(".log.old"))  # conserva 1 backup
        LOG_FILE.touch(exist_ok=True)
        LOG_FILE.chmod(0o600)   # el log tiene transcripciones -> solo el dueño
    except OSError:
        pass


_rotate_log()   # se chequea una vez por invocación (cada Win+Z es proceso nuevo)


def log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}\n"
    import sys
    sys.stderr.write(line)
    try:
        with LOG_FILE.open("a") as f:
            f.write(line)
    except OSError:
        pass


# Evento global de cancelación (lo setea cancel_handler vía SIGUSR2).
_cancel = threading.Event()

# Registro del subproceso actual (claude CLI) para poder matarlo al cancelar.
_current_proc: "subprocess.Popen | None" = None
_proc_lock = threading.Lock()

# Registro del streamer TTS actual (duck-typed: solo se le llama .cancel()).
_current_streamer = None
_streamer_lock = threading.Lock()


def set_current_proc(proc: "subprocess.Popen | None") -> None:
    global _current_proc
    with _proc_lock:
        _current_proc = proc


def kill_current_proc() -> None:
    """Mata el claude one-shot y SU GRUPO (se spawnea con start_new_session) ->
    al cancelar no quedan subspawns de claude-mem huérfanos. SIGTERM -> SIGKILL."""
    with _proc_lock:
        p = _current_proc
    if p is None or p.poll() is not None:
        return
    try:
        pgid = os.getpgid(p.pid)
        os.killpg(pgid, signal.SIGTERM)
        try:
            p.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            log("terminate ignored, SIGKILL al grupo")
            os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, OSError):
        try:
            p.kill()
        except Exception:
            pass


def set_current_streamer(s) -> None:
    global _current_streamer
    with _streamer_lock:
        _current_streamer = s


def cancel_streamer() -> None:
    with _streamer_lock:
        s = _current_streamer
    if s is not None:
        s.cancel()


def cancel_handler(_sig, _frame):
    log("ABORT signal received (SIGUSR2)")
    _cancel.set()
    kill_current_proc()
    cancel_streamer()
