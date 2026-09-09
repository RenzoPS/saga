"""Turno segmentado: el fix del bug "el orbe dice que habla pero no sale voz".

Causa original: un turno de Claude Code es `texto -> hueco de tools (100s+) -> texto`.
LiveKit lo modelaba como UN stream de LLM, el websocket del TTS de Deepgram quedaba
abierto durante el hueco y moría por inactividad (APITimeoutError). La respuesta final
llegaba a un canal muerto y no se escuchaba nada.

Se cubren dos cosas: la SEGMENTACIÓN (cada bloque se habla y se cierra por separado) y
la CONCURRENCIA (turnos solapados, cancelación, y que un turno viejo no pise al nuevo).
"""

import asyncio

from vc.claudecli import Ev
from lk import speech


# ── Protocolo del daemon -> Ev ────────────────────────────────────────────────
def _parse(o: dict):
    """Misma decisión que `_ask_via_daemon` sobre una línea del daemon."""
    if "delta" in o:
        return Ev("text", text=o["delta"])
    if "tool" in o:
        return Ev("tool", tool=o["tool"])
    if o.get("break"):
        return Ev("break")
    return None


def test_protocolo_daemon_mapea_los_tres_eventos():
    assert _parse({"delta": "hola"}) == Ev("text", text="hola")
    assert _parse({"tool": "Read"}) == Ev("tool", tool="Read")
    assert _parse({"break": True}) == Ev("break")
    assert _parse({"done": True}) is None


# ── Drenado en background ────────────────────────────────────────────────────
async def _drain_with(events, monkeypatch):
    """Corre `_ClaudeStream._drain` sobre `events` y devuelve (bloques, estados_orbe)."""
    from lk import claude_llm

    spoken: "list[str]" = []
    states: "list[str]" = []

    async def _fake_say(turn, chunks):
        # say() ahora recibe un async-iterable (streaming): consumilo como el TTS real.
        txt = chunks if isinstance(chunks, str) else "".join([c async for c in chunks])
        states.append("speak")
        spoken.append(txt)

    monkeypatch.setattr(claude_llm.speech, "say_block", _fake_say)
    monkeypatch.setattr(claude_llm.speech, "orb", lambda t, s: states.append(s))

    _DONE = object()
    q: asyncio.Queue = asyncio.Queue()
    for e in events:
        q.put_nowait(e)
    q.put_nowait(_DONE)

    turn = speech.Turn(gen=1)
    fut: asyncio.Future = asyncio.get_running_loop().create_future()
    fut.set_result(None)   # el "thread" ya terminó

    reader = claude_llm._TurnReader(q, _DONE, timeout=5.0)
    # `_drain` no toca `self` -> se puede invocar sin instanciar el stream de LiveKit.
    await claude_llm._ClaudeStream._drain(None, turn, reader, fut)
    return spoken, states, turn


def test_cada_bloque_se_habla_por_separado(monkeypatch):
    """Dos bloques separados por tools = dos say() = dos websockets cortos."""
    spoken, _, _ = asyncio.run(_drain_with([
        Ev("text", text="Ya encontré la carpeta."),
        Ev("tool", tool="Read"),
        Ev("break"),
        Ev("text", text="Listo, te armo el resumen."),
    ], monkeypatch))

    assert spoken == ["Ya encontré la carpeta.", "Listo, te armo el resumen."]


def test_entre_bloques_el_orbe_piensa_no_habla(monkeypatch):
    """El bug era mostrar 'hablando' durante el hueco. Debe decir 'think'."""
    _, states, _ = asyncio.run(_drain_with([
        Ev("text", text="Voy a mirar."),
        Ev("tool", tool="Grep"),
        Ev("break"),
        Ev("text", text="Encontré esto."),
    ], monkeypatch))

    assert states == ["think", "speak", "think", "speak", "idle"]
    assert states.count("speak") == 2    # solo cuando hay audio real


def test_las_tools_no_se_hablan(monkeypatch):
    """El nombre de la tool es para el log/orbe, nunca para el TTS."""
    spoken, _, _ = asyncio.run(_drain_with([
        Ev("tool", tool="Bash"),
        Ev("break"),
        Ev("tool", tool="Read"),
        Ev("break"),
        Ev("text", text="Che, terminé."),
    ], monkeypatch))

    assert spoken == ["Che, terminé."]


def test_turno_sin_texto_no_habla_ni_cuelga(monkeypatch):
    """Claude que solo corre tools y no dice nada: cierra igual, sin voz fantasma."""
    spoken, states, _ = asyncio.run(_drain_with([
        Ev("tool", tool="Bash"),
        Ev("break"),
    ], monkeypatch))

    assert spoken == []
    assert "speak" not in states
    assert states[-1] == "idle"


def test_varios_break_seguidos_no_parten_el_bloque(monkeypatch):
    """Un `break` sin texto acumulado no debe cerrar nada (bloque vacío)."""
    spoken, _, _ = asyncio.run(_drain_with([
        Ev("break"),
        Ev("break"),
        Ev("text", text="Una sola cosa."),
    ], monkeypatch))

    assert spoken == ["Una sola cosa."]


def test_al_terminar_corta_el_generador_del_thread(monkeypatch):
    """El drenado es dueño del thread: al salir, el Event queda seteado sí o sí."""
    _, _, turn = asyncio.run(_drain_with([Ev("text", text="listo")], monkeypatch))
    assert turn.cancel_ev.is_set()


# ── Concurrencia: turnos solapados ───────────────────────────────────────────
def _reset_speech():
    speech._current = None
    speech._gen = 0
    speech._session = None


def test_turno_nuevo_cancela_e_invalida_al_anterior():
    """Hablás mientras Claude sigue leyendo archivos: el viejo muere, el nuevo manda."""
    _reset_speech()
    viejo = speech.new_turn()
    nuevo = speech.new_turn()

    assert viejo.cancel_ev.is_set()        # se le cortó el generador bloqueante
    assert not nuevo.cancel_ev.is_set()
    assert speech._vigente(nuevo)
    assert not speech._vigente(viejo)


def test_un_turno_viejo_no_mueve_el_orbe(monkeypatch):
    """Sin esto, un turno cancelado pisa el estado visual del que recién arranca."""
    _reset_speech()
    seen: "list[str]" = []
    monkeypatch.setattr(speech, "orb_state", lambda s: seen.append(s))

    viejo = speech.new_turn()
    nuevo = speech.new_turn()

    speech.orb(viejo, "think")     # ignorado: ya no es vigente
    speech.orb(nuevo, "speak")

    assert seen == ["speak"]


def test_el_finally_de_un_turno_viejo_no_apaga_al_nuevo():
    """El `finally` del task cancelado corre DESPUÉS del cancel: no debe limpiar
    `_current` si ya lo reemplazaron, o el turno nuevo queda huérfano."""
    _reset_speech()

    async def _scenario():
        arranco = asyncio.Event()

        async def _lento():
            arranco.set()
            await asyncio.sleep(60)

        viejo = speech.new_turn()
        speech.start(viejo, _lento())
        await arranco.wait()
        assert speech.is_working()

        nuevo = speech.new_turn()          # cancela al viejo y toma su lugar
        await asyncio.sleep(0)             # dejá correr el finally del viejo
        await asyncio.sleep(0)

        assert speech._current is nuevo    # el viejo NO lo puso en None
        assert viejo.task.cancelled() or viejo.task.done()

    asyncio.run(_scenario())
    _reset_speech()


def test_cancel_deja_todo_apagado():
    """Win+Z en busy: se corta el thread, se corta el task, y no queda 'trabajando'."""
    _reset_speech()

    async def _scenario():
        async def _lento():
            await asyncio.sleep(60)

        t = speech.new_turn()
        speech.start(t, _lento())
        await asyncio.sleep(0)
        assert speech.is_working()

        speech.cancel()
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert t.cancel_ev.is_set()        # el generador bloqueante se corta
        assert not speech.is_working()
        assert speech._current is None

    asyncio.run(_scenario())
    _reset_speech()


def test_say_block_de_un_turno_viejo_no_habla():
    """Un bloque que llega tarde de un turno cancelado no debe sonar encima del nuevo."""
    _reset_speech()

    class _FakeSession:
        def __init__(self):
            self.dichos = []

        def say(self, text, allow_interruptions=True):
            self.dichos.append(text)
            raise AssertionError("un turno viejo no debería hablar")

    async def _scenario():
        speech.bind(_FakeSession())
        viejo = speech.new_turn()
        speech.new_turn()                  # lo reemplaza
        await speech.say_block(viejo, "texto viejo")   # no debe llamar say()

    asyncio.run(_scenario())
    _reset_speech()


# ── Latencia: el bloque se habla mientras se escribe ─────────────────────────
def test_el_bloque_arranca_sin_esperar_a_que_claude_termine():
    """El TTS tiene que arrancar con la primera oración. Acumular el bloque entero
    metía el tiempo de escritura de Claude (8-12s en una respuesta larga) como
    silencio previo a la primera palabra."""
    from lk import claude_llm

    async def _scenario():
        q: asyncio.Queue = asyncio.Queue()
        _DONE = object()
        reader = claude_llm._TurnReader(q, _DONE, timeout=5.0)
        gen = reader.deltas("Hola.")

        # Sale el primer chunk con la cola VACÍA: no espera el resto del bloque.
        assert await gen.__anext__() == "Hola."

        q.put_nowait(Ev("text", text=" Segundo."))
        assert await gen.__anext__() == " Segundo."

        q.put_nowait(Ev("break"))              # corte -> el websocket del TTS cierra acá
        try:
            await gen.__anext__()
            raise AssertionError("el bloque tendría que haber cerrado en el break")
        except StopAsyncIteration:
            pass

    asyncio.run(_scenario())


def test_el_bloque_cierra_en_la_tool_sin_esperar_el_break():
    """Cuando arranca una tool el texto ya terminó: soltá el websocket ahí mismo."""
    from lk import claude_llm

    async def _scenario():
        q: asyncio.Queue = asyncio.Queue()
        _DONE = object()
        reader = claude_llm._TurnReader(q, _DONE, timeout=5.0)
        gen = reader.deltas("Voy a mirar.")
        assert await gen.__anext__() == "Voy a mirar."
        q.put_nowait(Ev("tool", tool="Read"))
        try:
            await gen.__anext__()
            raise AssertionError("tendría que haber cerrado en la tool")
        except StopAsyncIteration:
            pass

    asyncio.run(_scenario())


# ── Red de seguridad: el turno no se cuelga para siempre ─────────────────────
def test_un_daemon_colgado_no_deja_el_turno_esperando_para_siempre(monkeypatch):
    """El camino segmentado CANCELA a propósito el watchdog de 60s (el trabajo con
    tools es legítimamente largo). Sin timeout propio, un daemon muerto dejaba a saga
    en "pensando" hasta que el usuario apretara Win+Z."""
    from lk import claude_llm

    spoken: "list[str]" = []
    states: "list[str]" = []

    async def _fake_say(turn, chunks):
        spoken.append("".join([c async for c in chunks]))

    monkeypatch.setattr(claude_llm.speech, "say_block", _fake_say)
    monkeypatch.setattr(claude_llm.speech, "orb", lambda t, s: states.append(s))

    async def _scenario():
        q: asyncio.Queue = asyncio.Queue()      # nunca llega `_DONE`: el daemon murió
        q.put_nowait(Ev("text", text="Voy a mirar."))
        q.put_nowait(Ev("tool", tool="Read"))

        turn = speech.Turn(gen=1)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        fut.set_result(None)

        reader = claude_llm._TurnReader(q, object(), timeout=0.05)
        await asyncio.wait_for(
            claude_llm._ClaudeStream._drain(None, turn, reader, fut),
            timeout=5.0,          # si el timeout interno no existe, esto explota
        )
        return states

    st = asyncio.run(_scenario())
    assert spoken == ["Voy a mirar."]     # habló lo que alcanzó a decir
    assert st[-1] == "idle"               # y CERRÓ el turno en vez de colgarse


def test_el_timeout_no_corta_un_bloque_que_sigue_llegando():
    """El timeout mide silencio ENTRE eventos, no duración total del turno: Claude
    puede tardar minutos en un turno largo mientras siga mandando texto."""
    from lk import claude_llm

    async def _scenario():
        q: asyncio.Queue = asyncio.Queue()
        _DONE = object()
        reader = claude_llm._TurnReader(q, _DONE, timeout=0.3)
        gen = reader.deltas("Uno.")
        assert await gen.__anext__() == "Uno."
        for texto in (" Dos.", " Tres.", " Cuatro."):
            await asyncio.sleep(0.15)       # menos que el timeout, varias veces seguidas
            q.put_nowait(Ev("text", text=texto))
            assert await gen.__anext__() == texto
        assert not reader.done

    asyncio.run(_scenario())


# ── Observabilidad: el transcript no puede llegar tarde ──────────────────────
def test_cada_bloque_se_loguea_al_escribirse_no_al_terminar_de_sonar(monkeypatch):
    """El log salía DESPUÉS del `wait_for_playout()` del último bloque: con 88s de
    audio, el transcript aparecía 88 segundos tarde. Ahora sale al cerrar el bloque."""
    from lk import claude_llm

    logged: "list[str]" = []
    monkeypatch.setattr(claude_llm, "log", lambda m: logged.append(m))

    async def _scenario():
        q: asyncio.Queue = asyncio.Queue()
        _DONE = object()
        reader = claude_llm._TurnReader(q, _DONE, timeout=5.0)
        gen = reader.deltas("Encontré el archivo.")
        await gen.__anext__()
        q.put_nowait(Ev("break"))
        try:
            await gen.__anext__()
        except StopAsyncIteration:
            pass
        # El bloque cerró; el log ya tiene que estar, sin haber reproducido nada.
        return [m for m in logged if m.startswith("[claude dice]")]

    dichos = asyncio.run(_scenario())
    assert dichos == ["[claude dice] Encontré el archivo."]


def test_el_reader_es_el_unico_que_toca_la_cola():
    """Regresión de diseño: antes `_next_text` y `_block` hacían `q.get()` cada uno.
    Funcionaba por serialización accidental; con generación especulativa (Flux eager
    EOT) esa fragilidad se paga. La cola tiene un solo dueño."""
    import ast
    import inspect
    from lk import claude_llm

    tree = ast.parse(inspect.getsource(claude_llm))

    def _lee_la_cola(nodo) -> bool:
        """`<algo>.get()` donde `<algo>` es una cola (`q` o `self._q`)."""
        if not (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute)):
            return False
        if nodo.func.attr != "get":
            return False
        obj = nodo.func.value
        if isinstance(obj, ast.Name) and obj.id == "q":
            return True
        return isinstance(obj, ast.Attribute) and obj.attr == "_q"

    culpables = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if any(_lee_la_cola(n) for n in ast.walk(fn)):
            culpables.add(fn.name)

    assert culpables == {"next_event"}, f"la cola tiene más de un dueño: {sorted(culpables)}"
