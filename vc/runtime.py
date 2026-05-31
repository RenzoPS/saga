"""Estado runtime + control de procesos: log, evento de cancelación, registros
de proceso/streamer actuales, signal handlers y helpers de PID-file.

Centraliza el estado mutable compartido para que el resto de los módulos no
dependan entre sí (evita ciclos de import)."""

import os
import signal
import subprocess
import threading
import time

from .config import PID_FILE, LOCK_FILE, LOG_FILE

_LOG_MAX = 512 * 1024  # 512KB -> rota a .old (evita crecimiento infinito)


def _rotate_log() -> None:
    try:
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > _LOG_MAX:
            LOG_FILE.replace(LOG_FILE.with_suffix(".log.old"))  # conserva 1 backup
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
    """SIGTERM primero (chance de cleanup), SIGKILL si no muere en 1s."""
    with _proc_lock:
        p = _current_proc
    if p is None or p.poll() is not None:
        return
    try:
        p.terminate()
    except ProcessLookupError:
        return
    except Exception as e:
        log(f"terminate EXC: {type(e).__name__}: {e}")
        return
    try:
        p.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        log("terminate ignored, sending SIGKILL")
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


# ---- helpers de PID-file (coordinacion entre invocaciones efimeras) ----
def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def read_pid_from(path):
    if not path.exists():
        return None
    try:
        pid = int(path.read_text().strip())
    except (ValueError, OSError):
        path.unlink(missing_ok=True)
        return None
    if not pid_alive(pid):
        path.unlink(missing_ok=True)
        return None
    return pid


def read_recorder_pid():
    return read_pid_from(PID_FILE)


def read_owner_pid():
    return read_pid_from(LOCK_FILE)


def signal_stop(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGUSR1)
    except ProcessLookupError:
        PID_FILE.unlink(missing_ok=True)


def signal_cancel(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGUSR2)
    except ProcessLookupError:
        LOCK_FILE.unlink(missing_ok=True)
