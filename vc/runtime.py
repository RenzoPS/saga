"""Estado runtime compartido: log rotativo + evento global de cancelación del turno.

Centraliza el estado mutable compartido para que el resto de los módulos no
dependan entre sí (evita ciclos de import)."""

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


# Evento global de cancelación del turno. Lo setea/limpia lk/claude_llm.py (path de
# cancel real en modo room) y lo chequea vc/claudecli.py entre chunks del stream.
_cancel = threading.Event()
