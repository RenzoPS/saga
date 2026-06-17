"""Adjuntos de la pestaña del orbe.

TEXTO: vive en MEMORIA del proceso agente (staging por el socket de control). El navegador lo
manda en vivo a orb_server, que reenvía `stage <b64>` al socket; el agente llama `stage_text()`.
No toca el filesystem.
IMAGEN: dead-drop por /tmp (binaria; Claude la lee como `screenshot_path`, mismo lifecycle que
el screenshot de grim). El navegador la sube por POST /attach?kind=image.

El agente (lk/claude_llm) consume el adjunto en el turno: antepone el texto al prompt y usa la
imagen como screenshot_path.

Consume-once: el texto se LEE y se LIMPIA acá; la imagen se devuelve como ruta y la borra el
worker tras mandarla a Claude. Todo corre en el hilo del event loop del agente (stage/take se
serializan ahí) -> no hace falta lock."""

from .config import ATTACH_IMG_PATH

# Texto staged en memoria (proceso agente). None = no hay nada. Lo setea el verbo `stage` del
# socket de control (lk/agent.py) y lo consume take_staged() en el turno.
_pending_text: "str | None" = None


def stage_text(text: "str | None") -> None:
    """Guarda el texto staged en memoria. Vacío/None -> lo limpia (el textarea quedó vacío)."""
    global _pending_text
    t = (text or "").strip()
    _pending_text = t or None


def clear_text() -> None:
    """Descarta el texto staged sin tocar la imagen. Lo usa el path de Shift+Enter: el texto ya
    viaja en el comando `say`, así que se limpia el staged para no consumirlo dos veces."""
    global _pending_text
    _pending_text = None


def has_staged() -> bool:
    """¿Hay algún adjunto (texto en memoria o imagen en /tmp) esperando consumirse?"""
    return _pending_text is not None or ATTACH_IMG_PATH.exists()


def take_staged() -> "tuple[str | None, object | None]":
    """Devuelve (texto, ruta_imagen) del adjunto y lo consume.

    El texto se lee de memoria y se limpia acá. La imagen se devuelve como Path si existe; NO se
    borra acá (la borra el caller tras mandarla a Claude). Sin nada: (None, None)."""
    global _pending_text
    text = _pending_text
    _pending_text = None
    img = ATTACH_IMG_PATH if ATTACH_IMG_PATH.exists() else None
    return text, img
