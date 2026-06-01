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


# ---- helpers de PID-file (coordinacion entre invocaciones efimeras) ----
def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _proc_starttime(pid: int) -> str:
    """starttime del proceso (campo 22 de /proc/pid/stat). Identifica una
    encarnación concreta de un PID -> distingue un PID reciclado de otro proceso."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            data = f.read()
        return data[data.rindex(")") + 1:].split()[19]   # tras comm: campo 22 = idx 19
    except (OSError, ValueError, IndexError):
        return ""


def self_identity() -> str:
    """Identidad propia 'pid:starttime' para lock/pid files (anti PID-recycle)."""
    pid = os.getpid()
    return f"{pid}:{_proc_starttime(pid)}"


def read_pid_from(path):
    """Devuelve el pid (int) si el dueño sigue vivo Y es la MISMA encarnación
    (valida starttime si el archivo lo tiene). Si no, limpia el archivo y None."""
    if not path.exists():
        return None
    try:
        raw = path.read_text().strip()
    except OSError:
        return None
    try:
        pid = int(raw.split(":", 1)[0])
    except ValueError:
        path.unlink(missing_ok=True)
        return None
    if not pid_alive(pid):
        path.unlink(missing_ok=True)
        return None
    if ":" in raw:   # validar starttime -> un PID reciclado no se hace pasar por el dueño
        start = raw.split(":", 1)[1]
        if start and start != _proc_starttime(pid):
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
