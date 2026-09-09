"""Lo que se ESCUCHÓ al cortarla, contra lo que Claude cree que dijo.

Saga tiene dos memorias que divergen al interrumpir: el `ChatContext` de LiveKit sabe lo que
sonó (lo trunca y marca `ChatMessage.interrupted`), y la sesión de Claude sabe lo que GENERÓ,
que es todo. Como `ClaudeCodeLLM` ignora el chat_ctx a propósito (el contexto multivuelta lo
maneja Claude), esa verdad nunca llegaba al cerebro: pedías "repetime lo último" y repetía
desde el texto completo.

`lk/heard.py` transporta ese dato por el hueco. Acá se cubre que lo transporte bien y que no
se quede pegado de un turno para otro.
"""

import pytest

from lk import heard


class _Msg:
    """Mínimo `ChatMessage`: rol, texto e `interrupted` (los tres que mira el módulo)."""

    def __init__(self, role, text, interrupted=False):
        self.role = role
        self.text_content = text
        self.interrupted = interrupted


class _Ctx:
    def __init__(self, *items):
        self.items = list(items)


@pytest.fixture(autouse=True)
def _limpio():
    heard.clear()
    yield
    heard.clear()


# ── Detección ────────────────────────────────────────────────────────────────
def test_una_respuesta_interrumpida_deja_nota():
    heard.note_from_context(_Ctx(
        _Msg("user", "contame el capitulo uno"),
        _Msg("assistant", "En el principio creó Dios los cielos", interrupted=True),
    ))
    nota = heard.take_note()

    assert nota is not None
    assert "En el principio creó Dios los cielos" in nota
    assert "interrumpió" in nota


def test_una_respuesta_completa_no_deja_nota():
    """Sin esto, cada turno arrastraría una aclaración que no viene al caso."""
    heard.note_from_context(_Ctx(
        _Msg("assistant", "Son las tres de la tarde.", interrupted=False),
    ))
    assert heard.take_note() is None


def test_un_contexto_sin_respuestas_no_rompe():
    heard.note_from_context(_Ctx(_Msg("user", "hola")))
    assert heard.take_note() is None


def test_mira_la_ULTIMA_respuesta_no_una_vieja():
    """Una interrupción de hace tres turnos ya no aplica."""
    heard.note_from_context(_Ctx(
        _Msg("assistant", "cortada hace rato", interrupted=True),
        _Msg("user", "dale"),
        _Msg("assistant", "esta salió entera", interrupted=False),
    ))
    assert heard.take_note() is None


def test_cortada_antes_de_la_primera_palabra():
    """Claude cree que respondió; el usuario no oyó nada. Igual hay que avisarle."""
    heard.note_from_context(_Ctx(_Msg("assistant", "", interrupted=True)))
    nota = heard.take_note()

    assert nota is not None
    assert "no dijiste nada" in nota


# ── Consume-once ─────────────────────────────────────────────────────────────
def test_la_nota_se_consume_una_sola_vez():
    """Vale para el turno siguiente a la interrupción y nada más."""
    heard.note_from_context(_Ctx(_Msg("assistant", "algo", interrupted=True)))

    assert heard.take_note() is not None
    assert heard.take_note() is None


def test_clear_descarta_la_nota_pendiente():
    """Colgar la llamada o resetear la sesión invalida la aclaración."""
    heard.note_from_context(_Ctx(_Msg("assistant", "algo", interrupted=True)))
    heard.clear()
    assert heard.take_note() is None


# ── El prompt no se infla con una respuesta larga cortada ────────────────────
def test_una_respuesta_larguisima_se_recorta_por_el_final():
    """Génesis 1 entero no tiene por qué volver en el prompt. Interesa DÓNDE quedó, o sea
    el final, no el principio."""
    largo = "palabra " * 500
    heard.note_from_context(_Ctx(_Msg("assistant", largo + "FINAL", interrupted=True)))
    nota = heard.take_note()

    assert "FINAL" in nota, "el recorte tiene que conservar el final, que es donde quedó"
    assert len(nota) < 1200


# ── Cableado: el hook y el consumo existen donde deben ───────────────────────
def test_el_agente_usa_el_hook_documentado_de_livekit():
    """`on_user_turn_completed` es el hook nativo: recibe el contexto YA truncado y ANTES
    del mensaje nuevo del usuario. Es el único momento con la información completa."""
    import inspect

    from lk import agent as lk_agent

    src = inspect.getsource(lk_agent.Assistant)
    assert "async def on_user_turn_completed" in src
    assert "heard.note_from_context" in src


def test_el_hook_respeta_la_firma_del_sdk():
    """Si LiveKit cambia la firma, el override deja de llamarse y el sintoma es mudo:
    ninguna nota, ningun error."""
    import inspect

    from livekit.agents import Agent

    from lk import agent as lk_agent

    base = inspect.signature(Agent.on_user_turn_completed)
    nuestro = inspect.signature(lk_agent.Assistant.on_user_turn_completed)
    assert list(nuestro.parameters) == list(base.parameters)


def test_la_nota_va_antes_de_la_consigna_en_el_prompt():
    """Claude tiene que corregir su memoria ANTES de leer lo que le pedís."""
    import inspect

    from lk import claude_llm

    src = inspect.getsource(claude_llm._ClaudeStream._run)
    assert 'prompt = f"{corte}\\n\\n{prompt}"' in src


# ── La nota NO puede dispararle acciones al agente ───────────────────────────
def test_la_nota_no_dispara_una_captura_de_pantalla():
    """EL BUG del 22/8, medido en una llamada real: `is_visual_command()` corría sobre el prompt
    YA compuesto con la nota. Claude estaba contando sobre San Nicolás de MIRA, `VISUAL_RE`
    matcheó "mira" dentro de la cita, y se mandó una captura de la pantalla del usuario.

    Tres turnos seguidos: 646 KB + 454 KB + 366 KB de imágenes metidas en la conversación por un
    "¿Para dónde?" sin ninguna intención visual. Contexto inflado y, peor, la pantalla del
    usuario viajando al modelo sin que la pidiera.

    La regla: citar no es pedir. El detector mira lo que dijo el USUARIO, nunca la nota."""
    from vc.session import is_visual_command

    dicho = "¿Para dónde?"
    nota = (
        "[Sistema: el usuario te interrumpió mientras hablabas. De tu respuesta anterior, lo "
        "ÚNICO que llegó a escuchar fue:\n\n«La base histórica es San Nicolás de Mira, un "
        "obispo que vivió en el siglo cuatro»\n\nEl resto lo escribiste pero nunca sonó.]"
    )

    assert not is_visual_command(dicho), "el usuario no pidió nada visual"
    assert is_visual_command(f"{nota}\n\n{dicho}"), "la nota sí contiene el gatillo (por eso el bug)"


def test_el_detector_visual_corre_sobre_el_pedido_y_no_sobre_el_prompt():
    """Regresión de la DECISIÓN, no del parseo: en `_run()` la variable que se le pasa al
    detector tiene que ser la de antes de pegar la nota. Si alguien vuelve a pasarle `prompt`,
    el bug de arriba revive y no se nota hasta que Claude nombre una ciudad llamada Mira."""
    import inspect
    import re

    from lk import claude_llm

    src = inspect.getsource(claude_llm)
    llamadas = re.findall(r"is_visual_command\((\w+)\)", src)

    assert llamadas, "no encontré la llamada al detector visual"
    assert all(v == "pedido" for v in llamadas), f"corre sobre {llamadas}, tiene que ser 'pedido'"
    # …y `pedido` tiene que capturarse ANTES de que la nota se pegue al prompt
    assert src.index("pedido = prompt") < src.index('prompt = f"{corte}'), \
        "pedido se toma después de meter la nota: ya viene contaminado"


def test_lo_que_pediste_vos_si_dispara_la_captura():
    """No pasarse de defensivo: si VOS decís "mirá la pantalla", la captura tiene que salir."""
    from vc.session import is_visual_command

    assert is_visual_command("mirá la pantalla y decime qué ves")
    assert is_visual_command("fijate esto que tengo acá en el editor")
