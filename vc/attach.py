"""Adjuntos pegados desde la pestaña del orbe (dead-drop por /tmp).

El navegador captura el paste (Ctrl+V) y lo manda por POST a orb_server, que escribe el
contenido en ATTACH_TEXT_PATH / ATTACH_IMG_PATH. El agente (lk/claude_llm) consume el
adjunto en el turno: antepone el texto al prompt y usa la imagen como screenshot_path.

Consume-once: el texto se LEE y se BORRA acá; la imagen se devuelve como ruta y la borra el
worker tras mandarla a Claude (mismo lifecycle que el screenshot de grim). /tmp es tmpfs (RAM)."""

from .config import ATTACH_TEXT_PATH, ATTACH_IMG_PATH


def has_staged() -> bool:
    """¿Hay algún adjunto pegado esperando consumirse?"""
    return ATTACH_TEXT_PATH.exists() or ATTACH_IMG_PATH.exists()


def take_staged() -> "tuple[str | None, object | None]":
    """Devuelve (texto, ruta_imagen) del adjunto y lo consume.

    El texto se lee y se borra acá. La imagen se devuelve como Path si existe; NO se borra
    acá (la borra el caller tras mandarla a Claude). Si no hay nada, devuelve (None, None)."""
    text = None
    try:
        if ATTACH_TEXT_PATH.exists():
            text = ATTACH_TEXT_PATH.read_text("utf-8").strip() or None
    except OSError:
        text = None
    finally:
        ATTACH_TEXT_PATH.unlink(missing_ok=True)

    img = ATTACH_IMG_PATH if ATTACH_IMG_PATH.exists() else None
    return text, img
