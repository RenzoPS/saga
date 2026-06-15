"""LLM custom de LiveKit que delega en Claude Code.

LiveKit ve un LLM normal (texto entra -> texto sale en deltas). Adentro reenvía el
ÚLTIMO mensaje del usuario al `claude_daemon` caliente vía `vc.claudecli.ask_claude_stream`
(con fallback a one-shot, igual que el flujo actual). Claude mantiene su PROPIA sesión y
system prompt en el store del CLI -> el contexto multivuelta no lo maneja LiveKit, lo
maneja Claude. Por eso ignoramos el chat_ctx salvo el último turno del usuario.
"""

import asyncio

from livekit.agents import llm, utils, APIConnectionError, DEFAULT_API_CONNECT_OPTIONS

from vc.claudecli import ask_claude_stream
from vc.runtime import log
from vc.session import is_visual_command
from vc.desktop import take_screenshot
from vc.orb import orb_state


def _last_user_text(chat_ctx: "llm.ChatContext") -> str:
    """Texto del último mensaje de rol 'user' del contexto de LiveKit."""
    items = chat_ctx.items
    if callable(items):  # defensivo: items puede ser propiedad o método según versión
        items = items()
    for item in reversed(list(items)):
        if getattr(item, "role", None) == "user":
            text = getattr(item, "text_content", None)
            if text:
                return text.strip()
    return ""


class ClaudeCodeLLM(llm.LLM):
    def __init__(self) -> None:
        super().__init__()

    def chat(
        self,
        *,
        chat_ctx: "llm.ChatContext",
        tools=None,
        conn_options=DEFAULT_API_CONNECT_OPTIONS,
        parallel_tool_calls=None,
        tool_choice=None,
        extra_kwargs=None,
    ) -> "llm.LLMStream":
        return _ClaudeStream(
            self,
            chat_ctx=chat_ctx,
            tools=tools or [],
            conn_options=conn_options,
        )


class _ClaudeStream(llm.LLMStream):
    async def _run(self) -> None:
        prompt = _last_user_text(self._chat_ctx)
        if not prompt:
            return

        loop = asyncio.get_running_loop()
        q: "asyncio.Queue" = asyncio.Queue()
        _DONE = object()

        def _worker() -> None:
            # ask_claude_stream es un generador BLOQUEANTE (daemon socket / subprocess).
            # Lo corremos en un thread y puenteamos los deltas a la cola asyncio.
            shot = None
            try:
                # Visión: si el prompt referencia algo visual ("mirá", "pantalla", etc.),
                # capturamos screenshot y se lo mandamos a Claude (va por el one-shot, que
                # maneja imagen). Igual que el flujo clásico: capturar -> mandar -> borrar.
                if is_visual_command(prompt):
                    shot = take_screenshot()
                    if shot is not None:
                        orb_state("screen")
                        log("[lk] keyword visual -> screenshot a Claude")
                for delta in ask_claude_stream(prompt, screenshot_path=shot):
                    loop.call_soon_threadsafe(q.put_nowait, delta)
            except Exception as e:  # noqa: BLE001 - se re-eleva en el lado async
                loop.call_soon_threadsafe(q.put_nowait, e)
            finally:
                if shot is not None:
                    shot.unlink(missing_ok=True)   # borrar captura (puede tener secretos en pantalla)
                loop.call_soon_threadsafe(q.put_nowait, _DONE)

        fut = loop.run_in_executor(None, _worker)
        chunk_id = utils.shortuuid()
        acc: "list[str]" = []
        try:
            while True:
                item = await q.get()
                if item is _DONE:
                    if acc:   # mostrar la respuesta de Claude en el panel de debug (monitor)
                        log("[claude dice] " + "".join(acc).strip())
                    break
                if isinstance(item, BaseException):
                    raise APIConnectionError() from item
                acc.append(item)
                self._event_ch.send_nowait(
                    llm.ChatChunk(
                        id=chunk_id,
                        delta=llm.ChoiceDelta(role="assistant", content=item),
                    )
                )
        finally:
            # Si LiveKit cancela el turno (interrupción/barge-in), cortamos el generador
            # de Claude vía el flag global de cancelación que ya respeta claudecli.
            if not fut.done():
                from vc.runtime import _cancel

                _cancel.set()
                try:
                    await fut
                finally:
                    _cancel.clear()
