"""Voz del turno SEGMENTADO (y su concurrencia).

Un turno de Claude Code no es un stream continuo: es
`texto -> hueco de tools (100s+) -> texto -> hueco -> texto`.

LiveKit modela el LLM como UN stream y el TTS de Deepgram mantiene el websocket
abierto mientras ese stream vive. En el hueco no llega texto, Deepgram lo mata por
inactividad (`APITimeoutError`, `ws.receive(timeout=conn_options.timeout)`), LiveKit
ve "ya mandé audio parcial, no reintento", y la respuesta final llega a un canal
muerto: el orbe queda en "hablando" y no se escucha nada. Ese era el bug.

Acá el turno se parte en BLOQUES: el primero lo habla el pipeline normal (el
`LLMStream` cierra en el `break`), y los siguientes los habla este módulo con
`session.say()` — primitiva nativa de LiveKit, no sintetizamos audio nosotros. Cada
bloque abre y cierra su propio websocket; el hueco pasa sin nada abierto.

CONCURRENCIA — el turno sobrevive al stream del LLM, así que dos turnos se pueden
solapar (hablás mientras Claude sigue leyendo archivos). Reglas:

  1. `new_turn()` numera cada turno. Solo el de número más alto es el VIGENTE.
  2. Un turno viejo nunca toca estado global ni mueve el orbe: todo pasa por
     `_vigente()`. Sin esto, el `finally` de un turno cancelado apaga al que recién
     arranca (se ejecuta DESPUÉS del `cancel()`, no en el momento).
  3. La cancelación corta las DOS puntas: el task async (`task.cancel()`) y el thread
     bloqueado en el socket del daemon (`cancel_ev`, un Event por turno). Cancelar
     solo el task dejaba el thread vivo bombeando a una cola que nadie lee, y el
     daemon ocupado con un turno que ya no le importa a nadie.
  4. El Event es POR TURNO, no el `vc.runtime._cancel` global: ese, con turnos
     solapados, mataba también al turno nuevo.
"""

import asyncio
import threading

from vc.runtime import log
from vc.orb import orb_state


class Turn:
    """Un turno de voz. `cancel_ev` corta el generador bloqueante que corre en el
    thread; `task` es el drenado async de los bloques que vienen después del primero."""

    __slots__ = ("gen", "cancel_ev", "task")

    def __init__(self, gen: int) -> None:
        self.gen = gen
        self.cancel_ev = threading.Event()
        self.task: "asyncio.Task | None" = None


_session = None
_gen = 0                        # sube en CADA turno: identifica al vigente
_current: "Turn | None" = None


def bind(session) -> None:
    """Registra la AgentSession activa (la llama `lk/agent.py` en el entry)."""
    global _session
    _session = session


def new_turn() -> Turn:
    """Abre un turno y mata el anterior. El nuevo pasa a ser el vigente ANTES de
    cancelar, así el `finally` del viejo ya se ve a sí mismo como no-vigente y no
    puede pisar nada de este."""
    global _gen, _current
    _gen += 1
    prev = _current
    _current = Turn(_gen)
    if prev is not None:
        _kill(prev)
    return _current


def _kill(t: Turn) -> None:
    t.cancel_ev.set()                       # corta el generador bloqueante (thread)
    if t.task is not None and not t.task.done():
        t.task.cancel()                     # corta el drenado async


def cancel() -> None:
    """Win+Z en busy: mata el trabajo en background vigente."""
    global _current
    if _current is not None:
        _kill(_current)
        _current = None


def is_working() -> bool:
    """True si el turno vigente sigue drenando en background (Claude usando tools
    con el stream del LLM ya cerrado). El orbe debe decir "pensando", no "idle"."""
    t = _current
    return t is not None and t.task is not None and not t.task.done()


def _vigente(t: Turn) -> bool:
    return t.gen == _gen and not t.cancel_ev.is_set()


def orb(t: Turn, state: str) -> None:
    """Mueve el orbe solo si `t` sigue siendo el turno vigente."""
    if _vigente(t):
        orb_state(state)


async def say_block(t: Turn, chunks) -> None:
    """Habla UN bloque con `session.say()`. `chunks` es un async-iterable de deltas:
    el TTS arranca con la primera oración en vez de esperar el bloque entero. El
    websocket vive lo que dura el bloque y se cierra al terminar: nunca cruza un hueco."""
    if not _vigente(t) or _session is None:
        await _aclose(chunks)   # nadie lo va a consumir: cerralo, no lo dejes colgado
        return
    orb(t, "speak")
    handle = _session.say(chunks, allow_interruptions=True)
    try:
        await handle.wait_for_playout()
    except asyncio.CancelledError:
        handle.interrupt()      # cortá el audio en curso, no lo dejes sonando huérfano
        await _aclose(chunks)
        raise


async def _aclose(chunks) -> None:
    aclose = getattr(chunks, "aclose", None)
    if aclose is not None:
        try:
            await aclose()
        except Exception:  # noqa: BLE001 - cerrar nunca puede romper el turno
            pass


def start(t: Turn, coro) -> None:
    """Corre el drenado del resto del turno en background."""

    async def _guard() -> None:
        try:
            await coro
        except asyncio.CancelledError:
            log("[speech] turno cancelado -> corto el drenado")
            raise
        except Exception as e:  # noqa: BLE001 - un turno no puede tumbar la sesión
            log(f"[speech] background EXC: {type(e).__name__}: {e}")
        finally:
            # Solo el turno vigente limpia: si ya lo reemplazaron, tocar `_current`
            # acá apagaría el turno NUEVO (este `finally` corre después del cancel).
            global _current
            if _current is t:
                _current = None

    t.task = asyncio.create_task(_guard())
