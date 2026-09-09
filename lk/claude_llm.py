"""LLM custom de LiveKit que delega en Claude Code.

LiveKit ve un LLM normal (texto entra -> texto sale en deltas). Adentro reenvía el
ÚLTIMO mensaje del usuario al `claude_daemon` caliente vía `vc.claudecli.ask_claude_stream`
(con fallback a one-shot, igual que el flujo actual). Claude mantiene su PROPIA sesión y
system prompt en el store del CLI -> el contexto multivuelta no lo maneja LiveKit, lo
maneja Claude. Por eso ignoramos el chat_ctx salvo el último turno del usuario.

TURNO SEGMENTADO: Claude Code no habla como un LLM. Emite un bloque de texto, se va a
usar tools 100s+, vuelve con otro bloque. Si dejamos UN solo `LLMStream` abierto todo
ese tiempo, el websocket del TTS muere de inactividad y la respuesta final no se
escucha (era el bug). Entonces: el PRIMER bloque sale por el pipeline normal y cerramos
el stream en el `break`; el resto del turno lo drena `lk/speech.py` en background,
hablando bloque por bloque y dejando el orbe en "pensando" durante los huecos.

La cola de eventos tiene UN SOLO dueño (`_TurnReader`). Antes la leían dos corrutinas
distintas y funcionaba por serialización accidental, no por diseño; con generación
especulativa (Flux eager EOT) esa fragilidad se paga.
"""

import asyncio

from livekit.agents import llm, utils, APIConnectionError, DEFAULT_API_CONNECT_OPTIONS

from lk import speech, heard
from vc.claudecli import ask_claude_stream, reset_claude
from vc.config import CLAUDE_DAEMON_TURN_TIMEOUT_S
from vc.runtime import log
from vc.session import is_visual_command, is_reset_command
from vc.desktop import take_screenshot
from vc.orb import orb_state
from vc.attach import take_staged


# Silencio máximo tolerado ENTRE eventos de Claude antes de dar el turno por colgado.
# Va por encima del techo propio del daemon: si el daemon vive, contesta (o falla) antes,
# así que esto sólo dispara cuando el daemon murió o quedó trabado sin avisar. Es la red
# que el camino segmentado NO tenía: ahí se cancela a propósito el watchdog de 60s (el
# trabajo con tools es legítimamente largo), y sin este timeout un cuelgue real dejaba a
# saga en "pensando" para siempre, hasta que el usuario apretara Win+Z.
_TURN_STALL_S = CLAUDE_DAEMON_TURN_TIMEOUT_S + 30


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


class _TurnReader:
    """Único consumidor de la cola de eventos del turno.

    Expone el turno como una secuencia de BLOQUES hablables, y cada bloque como un
    stream de deltas. Nadie más hace `q.get()`: así el orden de los eventos no depende
    de qué corrutina llegó primero.

    Cada bloque se loguea cuando Claude TERMINA DE ESCRIBIRLO, no cuando termina de
    reproducirse. Antes el transcript salía recién al final del turno entero: en una
    respuesta de 88s de audio, el log aparecía 88 segundos tarde.
    """

    __slots__ = ("_q", "_done_sentinel", "_timeout", "done", "error", "text")

    def __init__(self, q: "asyncio.Queue", done_sentinel, timeout: float) -> None:
        self._q = q
        self._done_sentinel = done_sentinel
        self._timeout = timeout
        self.done = False
        self.error: "BaseException | None" = None
        self.text: "list[str]" = []      # todo lo hablado en el turno, para el caller

    async def next_event(self):
        """Un evento de Claude, o `None` si el turno terminó, falló o se colgó."""
        if self.done:
            return None
        try:
            item = await asyncio.wait_for(self._q.get(), self._timeout)
        except asyncio.TimeoutError:
            log(f"[lk] Claude no manda eventos hace {self._timeout:.0f}s -> corto el turno colgado")
            self.done = True
            return None
        if item is self._done_sentinel:
            self.done = True
            return None
        if isinstance(item, BaseException):
            self.error = item
            self.done = True
            return None
        return item

    async def next_block(self) -> "str | None":
        """Primer texto del próximo bloque hablable. `None` = no queda nada que decir."""
        while True:
            item = await self.next_event()
            if item is None:
                return None
            if item.kind == "tool":
                log(f"[lk] tool -> {item.tool}")
                continue
            if item.kind == "break":
                continue          # bloque vacío: se fue a la tool sin hablar
            return item.text

    async def deltas(self, first: str):
        """Deltas del bloque en curso, para que el TTS arranque con la primera oración.
        Corta en tool/break/fin: ahí el websocket se cierra y nunca cruza el hueco."""
        block = [first]
        yield first
        try:
            while True:
                item = await self.next_event()
                if item is None:
                    return
                if item.kind == "tool":
                    log(f"[lk] tool -> {item.tool}")
                    return        # el texto ya cerró: soltá el websocket YA
                if item.kind == "break":
                    return
                block.append(item.text)
                yield item.text
        finally:
            # Corre al cerrarse el generador (fin normal o cancelación), o sea cuando
            # Claude terminó de ESCRIBIR el bloque — antes de que termine de sonar.
            self.text.extend(block)
            said = "".join(block).strip()
            if said:
                log("[claude dice] " + said)


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
        # Prompt del turno = adjunto de texto pegado (si hay) + consigna hablada.
        # take_staged() consume el adjunto: el texto se borra acá; la imagen se devuelve y la
        # borra el worker tras mandarla (igual que el screenshot). Imagen pegada > "mirá pantalla".
        voice = _last_user_text(self._chat_ctx)

        # Reset por voz ("nueva sesión", "empezamos de cero", etc.): enganchado en el turn
        # handler de LiveKit. Resetea la sesión de
        # Claude (el daemon respawnea) y cortamos el turno con una confirmación hablada, sin
        # mandar la consigna a Claude. No tocamos un adjunto pegado: take_staged() queda para
        # el próximo turno real.
        if is_reset_command(voice):
            reset_claude()
            heard.clear()   # sesión nueva: no arrastres la interrupción de la anterior
            log("[lk] reset por keyword de voz -> nueva sesión")
            orb_state("nueva")
            self._event_ch.send_nowait(
                llm.ChatChunk(
                    id=utils.shortuuid(),
                    delta=llm.ChoiceDelta(role="assistant", content="Listo, arrancamos de cero."),
                )
            )
            return

        clip_text, clip_img = take_staged()
        prompt = "\n\n".join(p for p in (clip_text, voice) if p)
        if not prompt and clip_img is None:
            heard.clear()   # turno vacío: la nota sigue valiendo para el próximo real
            return
        if not prompt:
            prompt = "Analizá la imagen que te adjunté."   # imagen sola, sin texto ni voz

        # Lo que pediste VOS, antes de que le peguemos nada del sistema. El detector de "mirá la
        # pantalla" mira ESTO y no el prompt final.
        #
        # EL BUG (medido el 22/8): la nota de interrupción cita el texto que Claude alcanzó a
        # decir, y `is_visual_command()` corría sobre el prompt YA compuesto. Claude estaba
        # contando sobre San Nicolás de MIRA -> `VISUAL_RE` matcheó "mira" dentro de la cita ->
        # se disparó una captura de pantalla. Tres turnos seguidos, 1.4 MB de imágenes metidas en
        # la conversación sobre un "¿Para dónde?" que no tenía nada de visual. La nota se
        # retroalimentaba con el detector.
        pedido = prompt

        # Si la cortaste hablando, Claude cree que dijo TODO (su sesión guarda lo que generó,
        # no lo que sonó). LiveKit sí sabe hasta dónde llegó la voz: esa nota viene de ahí.
        # Va PRIMERO para que corrija su memoria antes de leer la consigna. Ver lk/heard.py.
        corte = heard.take_note()
        if corte:
            prompt = f"{corte}\n\n{prompt}"

        # Turno nuevo: invalida y cancela el que pudiera seguir drenando en background.
        # Su Event propio (no el `_cancel` global) es lo que corta ESTE generador y
        # ningún otro — con turnos solapados, el global mataba también al nuevo.
        turn = speech.new_turn()

        loop = asyncio.get_running_loop()
        q: "asyncio.Queue" = asyncio.Queue()
        _DONE = object()

        def _put(item) -> None:
            # El thread puede sobrevivir al cierre del loop (job terminando): sin esta
            # guarda, call_soon_threadsafe tira RuntimeError y el finally no corre.
            try:
                loop.call_soon_threadsafe(q.put_nowait, item)
            except RuntimeError:
                pass

        def _worker() -> None:
            # ask_claude_stream es un generador BLOQUEANTE (daemon socket / subprocess).
            # Lo corremos en un thread y puenteamos los eventos a la cola asyncio.
            shot = clip_img   # imagen pegada (si hay) tiene prioridad sobre "mirá pantalla"
            try:
                if shot is not None:
                    orb_state("screen")
                    log("[lk] adjunto imagen -> a Claude")
                # Visión: si NO pegaste imagen pero VOS referenciaste algo visual ("mirá",
                # "pantalla", etc.), capturamos screenshot. Sobre `pedido`, NUNCA sobre `prompt`:
                # el prompt puede traer una nota del sistema citando a Claude, y citar no es pedir.
                elif is_visual_command(pedido):
                    shot = take_screenshot()
                    if shot is not None:
                        orb_state("screen")
                        log("[lk] keyword visual -> screenshot a Claude")
                for ev in ask_claude_stream(prompt, screenshot_path=shot, cancel=turn.cancel_ev):
                    _put(ev)
            except Exception as e:  # noqa: BLE001 - se re-eleva en el lado async
                _put(e)
            finally:
                if shot is not None:
                    shot.unlink(missing_ok=True)   # borrar captura/imagen pegada (consume-once; puede tener secretos)
                _put(_DONE)

        fut = loop.run_in_executor(None, _worker)
        reader = _TurnReader(q, _DONE, _TURN_STALL_S)
        chunk_id = utils.shortuuid()
        block: "list[str]" = []   # texto del PRIMER bloque (el que sale por el pipeline normal)
        handed_off = False        # ¿el resto del turno quedó en background?
        try:
            while True:
                item = await reader.next_event()
                if item is None:
                    if reader.error is not None:
                        raise APIConnectionError() from reader.error
                    break

                if item.kind == "tool":
                    log(f"[lk] tool -> {item.tool}")
                    continue

                if item.kind == "break":
                    # Claude terminó de hablar y se va a laburar. Si ya dijimos algo,
                    # CERRAMOS el stream acá: LiveKit sintetiza este bloque y cierra el
                    # websocket del TTS. El hueco de tools transcurre sin nada abierto.
                    if not block:
                        continue   # se fue a la tool sin decir nada: no hay bloque que cerrar
                    log("[lk] fin de bloque -> cierro voz, Claude sigue trabajando")
                    speech.start(turn, self._drain(turn, reader, fut))
                    handed_off = True
                    break

                block.append(item.text)
                self._event_ch.send_nowait(
                    llm.ChatChunk(
                        id=chunk_id,
                        delta=llm.ChoiceDelta(role="assistant", content=item.text),
                    )
                )
        finally:
            if block:
                reader.text.extend(block)
                log("[claude dice] " + "".join(block).strip())
            # Si LiveKit cancela el turno (interrupción/barge-in) cortamos el generador
            # de Claude con el Event de ESTE turno y esperamos a que el thread muera:
            # sin el await queda un thread bombeando a una cola que nadie lee y el daemon
            # ocupado con un turno que ya no le importa a nadie.
            # OJO: si hubo handoff, el turno NO terminó -> cancelar acá mataría a Claude
            # justo cuando se fue a leer los archivos. Lo cierra `_drain`.
            if not handed_off and not fut.done():
                turn.cancel_ev.set()
                await fut

    async def _drain(self, turn, reader: "_TurnReader", fut) -> None:
        """Resto del turno, en background: habla bloque por bloque, cada uno con su propio
        segmento de TTS. Entre bloques el orbe queda en "pensando" — que es la verdad:
        Claude está usando tools, no hablando.

        Es dueño del ciclo de vida del thread: pase lo que pase (fin normal, error,
        cancelación por Win+Z o por un turno nuevo) el generador se corta y el thread
        se espera antes de salir."""
        try:
            # `not reader.done` y no `while True`: cuando el último bloque consume el
            # fin del turno no hay que volver a pintar "pensando" para salir enseguida
            # a "idle" (parpadeo morado al cerrar cada respuesta).
            while not reader.done:
                speech.orb(turn, "think")   # hueco de trabajo: PENSANDO, no "hablando" mudo
                first = await reader.next_block()
                if first is None:
                    break                   # no queda nada hablable
                # STREAMING: el bloque se habla mientras Claude lo escribe. Acumularlo
                # entero antes de hablar metía el tiempo de escritura (8-12s en una
                # respuesta larga) como silencio previo a la primera palabra.
                await speech.say_block(turn, reader.deltas(first))
            speech.orb(turn, "idle")
        finally:
            # Pase lo que pase, el thread NO queda huérfano: cortá el generador y
            # esperalo. `shield` para que la espera sobreviva a nuestra cancelación
            # (si no, el thread seguiría vivo justo en el caso que queremos cerrar).
            turn.cancel_ev.set()
            if not fut.done():
                await asyncio.shield(fut)
