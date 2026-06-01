"""Sesión conversacional (uuid persistido) + detección de keywords de voz
(reset de sesión, referencia visual a la pantalla)."""

import os
import json
import time
import uuid as uuid_lib

import re

from .config import SESSION_FILE, RESET_KEYWORDS, VISUAL_RE, GOODBYE_KEYWORDS
from .runtime import log

_PUNCT_RE = re.compile(r"[.,!?¿¡;:\"'…\-]+")


def _atomic_write(path, text: str) -> None:
    """Escribe tmp + os.replace -> sin torn-read si otra invocación lee a la vez."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def _new_session_id() -> str:
    sid = str(uuid_lib.uuid4())
    _atomic_write(SESSION_FILE, json.dumps({"id": sid, "last_used": time.time()}))
    log(f"session new -> {sid}")
    return sid


def get_active_session_id() -> "tuple[str, bool]":
    """Devuelve (uuid, is_new). is_new=True si recien generado (no existe en Claude todavia).
    No hay timeout automatico: la sesion persiste hasta que el usuario pida reset por voz."""
    if SESSION_FILE.exists():
        try:
            data = json.loads(SESSION_FILE.read_text())
            sid = str(data["id"])
            log(f"session use -> {sid}")
            return sid, False
        except (json.JSONDecodeError, KeyError, ValueError, OSError) as e:
            log(f"session file corrupt: {e}, rotate")
    return _new_session_id(), True


def touch_session() -> None:
    if not SESSION_FILE.exists():
        return
    try:
        data = json.loads(SESSION_FILE.read_text())
        data["last_used"] = time.time()
        _atomic_write(SESSION_FILE, json.dumps(data))
    except (json.JSONDecodeError, KeyError, OSError) as e:
        log(f"touch_session fail (contexto no persistido): {type(e).__name__}: {e}")


def reset_session() -> str:
    return _new_session_id()


def is_reset_command(text: str) -> bool:
    norm = text.lower().strip().rstrip(".,!?¿¡ ")
    return any(k in norm for k in RESET_KEYWORDS)


def is_visual_command(text: str) -> bool:
    """Detecta si el prompt referencia algo que el usuario esta viendo en pantalla."""
    return VISUAL_RE.search(text) is not None


def is_goodbye(text: str) -> bool:
    """Cierre de conversación: el turno es CORTO (<=4 palabras, ya sin puntuación) y
    contiene una frase de despedida. El guard de longitud evita falsos positivos en
    consultas largas que mencionen 'gracias' ('gracias por explicarme tal cosa')."""
    norm = _PUNCT_RE.sub(" ", text.lower()).strip()
    norm = re.sub(r"\s+", " ", norm)
    if not norm:
        return False
    if len(norm.split()) > 4:
        return False
    return any(k in norm for k in GOODBYE_KEYWORDS)
