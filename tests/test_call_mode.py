"""Modo LLAMADA: conversación continua en vez de push-to-talk.

En push-to-talk cada turno es un ciclo completo (Win+Z, hablás, se apaga el mic, contesta,
idle). Eso es un walkie-talkie. En modo llamada la línea se abre UNA vez y queda abierta: el
fin de cada turno lo decide Deepgram Flux con señales acústicas Y lingüísticas, en vez de un
piso fijo de silencio que se pagaba entero en cada turno.

Se cubre la CONFIGURACIÓN, que es donde están los errores caros: un parámetro mal armado no
rompe en el import, rompe con un 400 del websocket a mitad de conversación.
"""

import pytest

from lk import agent as lk_agent
from vc import config


# ── turn_handling: quién decide el fin de turno ──────────────────────────────
def test_en_llamada_el_fin_de_turno_lo_decide_el_stt(monkeypatch):
    """`turn_detection="stt"` -> lo decide Flux. El piso fijo de silencio no va: es
    justamente el tiempo muerto que se paga en cada turno."""
    monkeypatch.setattr(lk_agent, "CALL_MODE", True)
    th = lk_agent._turn_handling()

    assert th["turn_detection"] == "stt"
    assert "endpointing" not in th, "en llamada no hay piso fijo de silencio"


def test_en_push_to_talk_sigue_decidiendo_el_vad(monkeypatch):
    """El modo viejo no se toca: Win+Z necesita que el turno lo cierres vos o el silencio."""
    monkeypatch.setattr(lk_agent, "CALL_MODE", False)
    th = lk_agent._turn_handling()

    assert th["turn_detection"] == "vad"
    assert th["endpointing"]["min_delay"] == 1.2


@pytest.mark.parametrize("call_mode", [True, False])
def test_la_interrupcion_es_vad_local_en_los_dos_modos(monkeypatch, call_mode):
    """`adaptive` no se puede usar self-hosted: `AdaptiveInterruptionDetector` se construye
    contra LIVEKIT_INFERENCE_URL/API_KEY (LiveKit Cloud). Saga corre un server LOCAL -> el
    detector no se crea y la sesión cae sola a `vad` con un warning. Pedirlo igual no rompe,
    pero miente sobre lo que está activo."""
    monkeypatch.setattr(lk_agent, "CALL_MODE", call_mode)
    assert lk_agent._turn_handling()["interruption"]["mode"] == "vad"


def test_el_detector_adaptativo_sigue_necesitando_la_nube():
    """Se rompe SOLO el día que LiveKit permita correr el detector adaptativo sin su gateway
    de inferencia. Ese día conviene volver a `adaptive` + `backchannel_boundary`, que es lo
    único que distingue un "dale" de un corte real. Hasta entonces, `vad` + filtros locales."""
    import inspect

    from livekit.agents.inference.interruption import AdaptiveInterruptionDetector

    src = inspect.getsource(AdaptiveInterruptionDetector.__init__)
    assert "LIVEKIT_INFERENCE_API_KEY" in src or "get_default_inference_url" in src


@pytest.mark.parametrize("call_mode", [True, False])
def test_retoma_si_la_interrupcion_fue_falsa(monkeypatch, call_mode):
    """Con el mic siempre abierto, una tos o un ruido dispara el VAD sin que hayas dicho
    nada. Sin esto, saga se come la respuesta a medio decir."""
    monkeypatch.setattr(lk_agent, "CALL_MODE", call_mode)
    interruption = lk_agent._turn_handling()["interruption"]

    assert interruption["resume_false_interruption"] is True
    assert interruption["false_interruption_timeout"] > 0


@pytest.mark.parametrize("call_mode", [True, False])
def test_una_palabra_suelta_no_corta_la_respuesta(monkeypatch, call_mode):
    """EL BUG del 21/8: `min_words` estaba en el default de LiveKit (0), así que UNA palabra
    mal transcripta cortaba una respuesta de 20 segundos. Y cada corte mata el proceso de
    Claude -> el turno siguiente paga un `--resume` en frío (ttft 8.0s contra 1.7s normal).
    Resultado medido: contó 4 veces la misma anécdota del Imperio romano sin avanzar nunca."""
    monkeypatch.setattr(lk_agent, "CALL_MODE", call_mode)
    assert lk_agent._turn_handling()["interruption"]["min_words"] >= 2


def test_el_umbral_de_palabras_no_te_deja_sin_poder_cortarla():
    """El otro lado del mismo filtro: las interrupciones REALES son cortas ("pará",
    "callate", "esperá"). Un umbral alto te deja escuchando una respuesta de 30s sin salida."""
    assert config.INTERRUPTION_MIN_WORDS <= 3


@pytest.mark.parametrize("call_mode", [True, False])
def test_la_interrupcion_exige_voz_sostenida(monkeypatch, call_mode):
    """`min_duration` es el piso que explica los end_of_utterance_delay clavados en 0.500s
    del log: no era Flux decidiendo, era este umbral. Se deja en el default de LiveKit, pero
    explícito y por env, porque es la perilla contra los cortes por ruido corto."""
    monkeypatch.setattr(lk_agent, "CALL_MODE", call_mode)
    assert lk_agent._turn_handling()["interruption"]["min_duration"] >= 0.5


@pytest.mark.parametrize("call_mode", [True, False])
def test_la_generacion_especulativa_de_livekit_queda_apagada(monkeypatch, call_mode):
    """Una sola fuente de especulación. La de LiveKit corre sobre transcripts PARCIALES y
    hace multi-commit contra el bridge bloqueante del daemon -> turnos partidos sin
    respuesta (turn-flow.md). La que sí queremos es la de Flux (`eager_eot`), que cancela
    vía TurnResumed ANTES de commitear."""
    monkeypatch.setattr(lk_agent, "CALL_MODE", call_mode)
    assert lk_agent._turn_handling()["preemptive_generation"]["enabled"] is False


# ── Flux: los parámetros que Deepgram rechaza con 400 ───────────────────────
def test_el_modelo_multilingue_es_el_unico_que_acepta_language_hint():
    """`language_hint` sobre `flux-general-en` devuelve
    `400 INVALID_PARAMETER`. Es un error que NO se ve hasta que alguien habla."""
    if config.FLUX_LANGUAGE_HINTS:
        assert config.FLUX_MODEL == "flux-general-multi"


def test_hay_hint_de_espanol():
    """Sin hints auto-detecta; con hints da precisión de modelo monolingüe. Acá se habla
    español mezclado con términos técnicos en inglés -> los dos hints."""
    assert "es" in config.FLUX_LANGUAGE_HINTS


def test_los_umbrales_estan_en_el_rango_que_acepta_deepgram():
    """Fuera de rango es 400. Documentado: eot 0.5–0.9, eager 0.3–0.9, timeout 500–60000ms."""
    assert 0.5 <= config.FLUX_EOT_THRESHOLD <= 0.9
    assert 0.3 <= config.FLUX_EAGER_EOT_THRESHOLD <= 0.9
    assert 500 <= config.FLUX_EOT_TIMEOUT_MS <= 60000


def test_el_eager_arranca_conservador():
    """Más bajo = menos latencia pero más falsos arranques, y cada falso arranque es una
    cancelación de turno: el camino que ya rompió todo con preemptive_generation. Se baja
    midiendo, no de una."""
    assert config.FLUX_EAGER_EOT_THRESHOLD >= 0.5


def test_la_url_repite_language_hint_en_vez_de_juntarlo_con_comas():
    """Deepgram espera `language_hint=es&language_hint=en`. Si el plugin los uniera con
    coma, el server rechaza el código de idioma `es,en` con 400."""
    from livekit.plugins.deepgram._utils import _to_deepgram_url

    url = _to_deepgram_url(
        {"model": config.FLUX_MODEL, "language_hint": config.FLUX_LANGUAGE_HINTS},
        base_url="wss://api.deepgram.com/v2/listen",
        websocket=True,
    )

    assert url.count("language_hint=") == len(config.FLUX_LANGUAGE_HINTS)
    assert "language_hint=es%2Cen" not in url and "language_hint=es,en" not in url


def test_no_donamos_el_audio_al_programa_de_mejora_de_deepgram():
    """El default del plugin es `mip_opt_out=False`: tu audio puede usarse para entrenar. Por
    este mic pasa conversación privada, nombres de clientes y contenido de repos. Opt-out por
    default; que salga del default hace falta pedirlo con SAGA_FLUX_MIP=1."""
    assert config.FLUX_MIP_OPT_OUT is True


def test_el_stt_de_flux_manda_el_opt_out_y_el_keyterm_no_deprecado(monkeypatch):
    """Dos cosas en la misma construcción: que el opt-out LLEGUE al plugin (un flag de
    privacidad que se queda en config no protege nada), y `keyterm` en vez de `keyterms`
    (el plural está deprecado y logueaba un warning en cada arranque)."""
    visto = {}

    class _FakeSTTv2:
        def __init__(self, **kw):
            visto.update(kw)

    monkeypatch.setattr(lk_agent, "CALL_MODE", True)
    monkeypatch.setattr(lk_agent, "_HAS_DEEPGRAM", True)
    monkeypatch.setattr(lk_agent.deepgram, "STTv2", _FakeSTTv2)
    lk_agent._build_stt(vad=None)

    assert visto["mip_opt_out"] is True
    assert visto["keyterm"] == config.FLUX_KEYTERMS
    assert "keyterms" not in visto, "el plural está deprecado en el plugin de Deepgram"


# ── Deprecaciones del framework ──────────────────────────────────────────────
def test_no_usamos_room_input_options_deprecado():
    """`RoomInputOptions`/`RoomOutputOptions` mueren en livekit-agents v2.0; el reemplazo es
    `RoomOptions`, que tiene el mismo `close_on_disconnect` que necesitamos para que el socket
    de control sobreviva a un reload de la pestaña del orbe."""
    import inspect
    import pathlib

    # Se mira el USO, no la palabra: el módulo la nombra en un comentario que explica por qué
    # migró, y ese comentario es justamente lo que no queremos que se borre.
    src = pathlib.Path(inspect.getfile(lk_agent)).read_text()
    codigo = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))

    assert "RoomInputOptions" not in codigo
    assert "room_options=RoomOptions(close_on_disconnect=False)" in codigo


def test_room_options_sigue_teniendo_close_on_disconnect():
    """Si el campo desapareciera, la pestaña del orbe volvería a matar el job al recargarse
    y Win+Z daría ConnectionRefusedError. Falla en el upgrade, no en vivo."""
    from livekit.agents.voice.room_io import RoomOptions

    assert RoomOptions(close_on_disconnect=False).close_on_disconnect is False


# ── El socket de control no se lo puede llevar otro proceso ──────────────────
def test_la_limpieza_del_socket_no_se_registra_al_importar():
    """EL BUG del 21/8, reproducido: `atexit.register(...)` estaba en el CUERPO del módulo, así
    que corría en cualquier proceso que importara `lk.agent`. LiveKit prewarmea procesos de
    repuesto que importan el módulo y nunca atienden un job (visto: pid 980738); cuando uno moría,
    su atexit borraba el socket del job VIVO.

    Síntoma medido: la llamada seguía andando (el agente contestó turnos hasta 16s después) pero
    Win+Z tiraba `FileNotFoundError` -> mic abierto SIN forma de colgar desde la tecla."""
    import ast
    import inspect
    import pathlib

    arbol = ast.parse(pathlib.Path(inspect.getfile(lk_agent)).read_text())
    for nodo in arbol.body:      # SOLO el top-level: adentro de una función está bien
        if isinstance(nodo, ast.Expr) and isinstance(nodo.value, ast.Call):
            f = nodo.value.func
            nombre = getattr(f, "attr", None) or getattr(f, "id", None)
            assert nombre != "register", "atexit.register a nivel de módulo: se lo lleva el prewarm"


def test_solo_borra_el_socket_el_proceso_que_lo_bindeo(tmp_path, monkeypatch):
    """La otra mitad: aunque se registre bien, si otro job ya rebindeó el path, el archivo en
    disco es de OTRO dueño. Borrarlo repite el mismo bug por otro camino, así que se compara el
    inodo contra el que bindeamos nosotros."""
    sock = tmp_path / "ctl.sock"
    monkeypatch.setattr(lk_agent, "LK_CTL_SOCK", sock)

    registrados = []
    monkeypatch.setattr(lk_agent.atexit, "register", registrados.append)

    sock.write_text("el mio")
    lk_agent._armar_limpieza_del_socket()

    # otro job rebindeó el path: mismo nombre, archivo distinto
    sock.unlink()
    sock.write_text("el de otro job")

    registrados[0]()
    assert sock.exists(), "borró el socket de otro dueño"


def test_el_dueno_del_socket_si_lo_limpia(tmp_path, monkeypatch):
    """No pasarse de defensivo: un socket huérfano en /tmp tiene que irse igual."""
    sock = tmp_path / "ctl.sock"
    monkeypatch.setattr(lk_agent, "LK_CTL_SOCK", sock)

    registrados = []
    monkeypatch.setattr(lk_agent.atexit, "register", registrados.append)

    sock.write_text("el mio")
    lk_agent._armar_limpieza_del_socket()
    registrados[0]()

    assert not sock.exists()


# ── La línea abierta no queda viva sola ──────────────────────────────────────
def test_la_llamada_tiene_techo_de_inactividad():
    """Un mic abierto indefinidamente frente a una IA agéntica con permisos `auto` es una
    superficie que no queremos dejar viva cuando no hay nadie usándola."""
    assert 0 < config.CALL_IDLE_TIMEOUT_S <= 600


def test_el_modo_por_defecto_es_push_to_talk():
    """El modo llamada se elige; no se hereda por sorpresa tras un pull."""
    import importlib

    import vc.config as cfg

    monkey = importlib.reload(cfg)
    assert monkey.SAGA_MODE in ("ptt", "call")   # el env de la sesión manda
    # …pero sin env, el default del código es push-to-talk:
    import os

    assert os.environ.get("SAGA_MODE") is not None or monkey.SAGA_MODE == "ptt"


def test_un_modo_invalido_cae_a_push_to_talk(monkeypatch):
    """Un typo en la env var no puede dejar el mic abierto sin que nadie lo haya pedido."""
    import importlib

    monkeypatch.setenv("SAGA_MODE", "llamda")   # typo a propósito
    import vc.config as cfg

    recargado = importlib.reload(cfg)
    assert recargado.SAGA_MODE == "ptt"
    assert recargado.CALL_MODE is False
    monkeypatch.delenv("SAGA_MODE", raising=False)
    importlib.reload(cfg)


# ── Un turno que falla NO puede destruir la conversación ─────────────────────
def _clasificar(result_msg: dict) -> str:
    """Misma decisión que `claude_daemon._one_turn` sobre el mensaje `result`."""
    if not result_msg.get("is_error"):
        return "ok"
    return "session_error" if result_msg.get("num_turns", 0) == 0 else "turn_error"


def test_una_sesion_que_no_existe_si_se_respawnea():
    """`--resume` a una uuid muerta: el turno nunca corre (num_turns=0). Ahí sí hay que
    arrancar de cero, porque no hay nada que preservar. Forma real verificada contra el CLI."""
    muerta = {
        "type": "result", "subtype": "error_during_execution", "is_error": True,
        "num_turns": 0, "duration_ms": 0,
    }
    assert _clasificar(muerta) == "session_error"


def test_un_turno_que_falla_con_la_sesion_viva_no_la_resetea():
    """EL BUG: `is_error` atrapaba tope de tokens, sobrecarga de API, tools que fallan…
    y todos terminaban en `spawn(fresh=True)` -> uuid nueva -> CONTEXTO DESTRUIDO en
    silencio, a mitad de una llamada.

    Visto en vivo: Claude recitó Génesis 1 entero, el turno fallo, y el
    '¿como se llama el capitulo?' siguiente llego a un Claude recien nacido que se puso a
    buscar 'biblia' en el repo."""
    fallo_con_sesion_viva = {
        "type": "result", "subtype": "error_during_execution", "is_error": True,
        "num_turns": 3, "duration_ms": 12548,
    }
    assert _clasificar(fallo_con_sesion_viva) == "turn_error"


def test_un_turno_ok_no_toca_nada():
    assert _clasificar({"type": "result", "subtype": "success",
                        "is_error": False, "num_turns": 2}) == "ok"


def test_el_daemon_no_respawnea_fresco_ante_turn_error():
    """Regresion de la decision, no del parseo: `turn()` tiene que cortar en 'turn_error'
    ANTES de llegar al respawn fresco."""
    import inspect
    import pathlib

    src = pathlib.Path(
        inspect.getfile(inspect.currentframe())
    ).parent.parent.joinpath("claude_daemon.py").read_text()

    i_turn_error = src.index('if res == "turn_error"')
    i_respawn = src.index('if attempt == 1 and res in ("session_error", "dead")')
    assert i_turn_error < i_respawn, "el turn_error tiene que cortar antes del respawn fresco"


# ── El wake word no puede colgar la llamada ──────────────────────────────────
def test_el_wake_no_usa_el_mismo_callback_que_la_tecla():
    """"hey saga" significa QUIERO HABLARTE, nunca "colgá". El wake compartía callback con
    Win+Z, y en modo llamada un `press` con la línea abierta es COLGAR -> un disparo del wake
    mataba la conversación. Con el umbral bajo pasa con ruido: visto en un E2E, confianza 0.11
    cortó la llamada a los 4 segundos. La tecla puede significar las dos cosas porque la
    apretás a propósito; el wake no."""
    import inspect

    from lk import agent as lk_agent

    src = inspect.getsource(lk_agent.entry)
    assert "on_wake=_on_wake" in src, "el wake tiene que tener su propio callback"
    assert "on_wake=_press" not in src, "el wake no puede compartir callback con Win+Z"


def test_el_wake_en_llamada_es_un_no_op():
    """La guarda mira la fase: si ya hay línea abierta, el wake no hace nada."""
    import inspect

    from lk import agent as lk_agent

    src = inspect.getsource(lk_agent.entry)
    cuerpo = src[src.index("def _on_wake()"):src.index("def _start_wake_on_track")]
    assert 'phase["v"] == "call"' in cuerpo
    assert "return" in cuerpo


# ── El cerebro es intercambiable ─────────────────────────────────────────────
def test_el_cerebro_por_defecto_es_claude_code():
    """Gemini es un modo para medir; lo agéntico no se pierde por descuido tras un pull."""
    import os

    assert os.environ.get("SAGA_LLM") is not None or config.SAGA_LLM == "claude"


def test_un_cerebro_invalido_cae_a_claude(monkeypatch):
    import importlib

    monkeypatch.setenv("SAGA_LLM", "gpt-inventado")
    import vc.config as cfg

    assert importlib.reload(cfg).SAGA_LLM == "claude"
    monkeypatch.delenv("SAGA_LLM", raising=False)
    importlib.reload(cfg)


def test_el_prompt_de_gemini_no_promete_tools():
    """Prometerle tools a un modelo que no las tiene lo hace inventar que ya actuó, que es
    peor que decir 'no puedo'."""
    assert "NO tenes tools" in config.GEMINI_SYSTEM_PROMPT
    assert "Sos agentica" not in config.GEMINI_SYSTEM_PROMPT
    assert "SEGURIDAD" not in config.GEMINI_SYSTEM_PROMPT   # habla de acciones que no puede hacer


def test_el_prompt_de_claude_conserva_lo_agentico():
    """El refactor en secciones no puede haberle sacado capacidades al cerebro real."""
    assert "Sos agentica" in config.CLAUDE_SYSTEM_PROMPT
    assert "SEGURIDAD" in config.CLAUDE_SYSTEM_PROMPT
    assert "CONFIRMACION EN DOS PASOS" in config.CLAUDE_SYSTEM_PROMPT


def test_el_modelo_de_gemini_es_un_lite_con_version_concreta():
    """Los Flash dan 20 requests por DÍA en el free tier y los Lite 500: en voz cada turno es
    un request. Y versión concreta, no el alias `-latest`, que puede cambiar de modelo a mitad
    de una llamada y dar un 'de golpe responde distinto' imposible de atribuir."""
    assert "lite" in config.GEMINI_MODEL
    assert not config.GEMINI_MODEL.endswith("-latest")
