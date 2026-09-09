"""Qué se ESCUCHÓ realmente cuando la cortaste a mitad de una frase.

EL PROBLEMA
-----------
Saga tiene DOS memorias que no coinciden cuando hay una interrupción:

  - El `ChatContext` de LiveKit sabe lo que sonó por el parlante. Al interrumpir, el framework
    "truncates its conversation history to reflect only what the user heard" y marca el mensaje
    con `ChatMessage.interrupted = True`.
  - La sesión de Claude (adentro del CLI) sabe lo que GENERÓ, que es todo, porque para él nunca
    lo cortaron.

Y saga usa la segunda: `ClaudeCodeLLM` ignora el `chat_ctx` a propósito, porque el contexto
multivuelta lo maneja Claude, no LiveKit. Ese desvío es lo que nos da el cerebro agéntico, y es
también lo que rompe esto: le pedís "repetime lo último" y repite desde el texto completo, no
desde donde lo cortaste.

LA SOLUCIÓN
-----------
Leer del `chat_ctx` truncado lo único que LiveKit sabe y Claude no —hasta dónde llegó la voz—
y pasárselo a Claude como una nota en el próximo turno.

No reimplementamos la truncación: ya la hace el framework. Solo la transportamos por el hueco
que abre nuestra propia arquitectura.

Consume-once, igual que `vc.attach`: la nota vale para el turno INMEDIATAMENTE siguiente a la
interrupción y se limpia al leerla. Si no, cada turno posterior arrastraría una aclaración que
ya no viene al caso.
"""

from vc.runtime import log

# Lo último que el usuario ALCANZÓ A ESCUCHAR de una respuesta cortada. None = no hay nada
# pendiente. Lo setea el hook `on_user_turn_completed` (lk/agent.py) y lo consume el turno
# siguiente en `lk/claude_llm.py`. Todo corre en el mismo event loop -> no hace falta lock.
_pending: "str | None" = None

# Recortamos lo que se le manda a Claude: alcanza con el final para que sepa dónde quedó, y una
# respuesta larga cortada (Génesis 1, por ejemplo) no tiene por qué volver entera en el prompt.
_MAX_CHARS = 600


def _last_assistant_message(turn_ctx):
    """Último mensaje del asistente en el contexto, o None."""
    items = turn_ctx.items
    if callable(items):   # defensivo: puede ser propiedad o método según versión
        items = items()
    for item in reversed(list(items)):
        if getattr(item, "role", None) == "assistant":
            return item
    return None


def note_from_context(turn_ctx) -> None:
    """Si la respuesta anterior quedó cortada, guardar lo que sí se escuchó.

    Se llama desde `Agent.on_user_turn_completed`, que recibe el contexto YA truncado y
    ANTES del mensaje nuevo del usuario: justo el momento en que LiveKit sabe qué se oyó.
    """
    global _pending
    msg = _last_assistant_message(turn_ctx)
    if msg is None or not getattr(msg, "interrupted", False):
        _pending = None       # el turno anterior terminó entero: no hay nada que aclarar
        return

    oido = (getattr(msg, "text_content", None) or "").strip()
    if not oido:
        # La cortaste antes de la primera palabra: Claude no dijo nada audible. Vale la pena
        # que lo sepa igual, porque él cree que respondió.
        _pending = ""
        log("[heard] interrumpida antes de la primera palabra")
        return

    if len(oido) > _MAX_CHARS:
        oido = "…" + oido[-_MAX_CHARS:]
    _pending = oido
    log(f"[heard] interrumpida; se escuchó hasta: …{oido[-60:]!r}")


def take_note() -> "str | None":
    """Nota para el prompt del próximo turno, y la consume. None si no hubo interrupción.

    El texto está redactado para que Claude lo entienda como corrección de su propia memoria:
    él cree que dijo todo, y esto le dice hasta dónde llegó de verdad.
    """
    global _pending
    oido, _pending = _pending, None
    if oido is None:
        return None
    if oido == "":
        return ("[Sistema: el usuario te interrumpió antes de que se escuchara una sola palabra "
                "de tu respuesta anterior. Para él, no dijiste nada.]")
    return (
        "[Sistema: el usuario te interrumpió mientras hablabas. De tu respuesta anterior, lo "
        f"ÚNICO que llegó a escuchar fue:\n\n«{oido}»\n\n"
        "El resto lo escribiste pero nunca sonó. Si te pide repetir, aclarar o continuar lo "
        "último que dijiste, tomá como referencia ESE texto, no el completo.]"
    )


def clear() -> None:
    """Descarta la nota pendiente (reset de sesión, colgar la llamada)."""
    global _pending
    _pending = None
