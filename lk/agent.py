"""Entrypoint del modo LiveKit (push-to-talk).

LiveKit-agents es dueño del runtime de audio: captura, streaming, chunks, VAD,
barge-in. Nosotros enchufamos las piezas:
  - STT  -> Deepgram Nova-3 streaming (default); whisper local si no hay key.
  - LLM  -> Claude Code (vía claude_daemon).
  - TTS  -> Deepgram Aura-2 voz es (default); edge-tts si no hay key.
La elección la decide la presencia de DEEPGRAM_API_KEY (.env.local), NO un flag.

Fin de turno por SILENCIO (turn_detection="vad", ~2s). Win+Z es una máquina de 3
fases:
  - idle -> graba (mic ON)
  - rec  -> corta y manda el turno (commit_user_turn)
  - busy -> mata la respuesta en curso (interrupt) y vuelve a idle
Win+Z (otro proceso) habla con el agente por un socket Unix (LK_CTL_SOCK) mandando
"press"; el server del socket corre en el MISMO loop que la sesión -> llama la API
de LiveKit directo.

Transporte ÚNICO: ROOM (livekit-server local + browser cliente). El audio llega por el
track del BROWSER (cliente orbe); en room el track detached DESCARTA frames
(room_io/_input.py) -> NO hay backlog. El wake (opt-in, U4) corre acá en el SERVER sobre
el track del mic (WakeWordTrackDetector), reusando el modelo Python.
        .venv/bin/python lk/agent.py start      # usa LIVEKIT_URL/API_KEY/API_SECRET (.env.local)
"""

import os
import sys
import atexit
import base64
import asyncio

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from livekit import agents, rtc
from livekit.agents import AgentServer, AgentSession, Agent, APIConnectOptions
# `RoomOptions` reemplaza a RoomInputOptions/RoomOutputOptions (deprecados, mueren en v2.0). No se
# exporta en el top-level de `livekit.agents` todavía -> se importa del submódulo.
from livekit.agents.voice.room_io import RoomOptions
from livekit.agents.voice.agent_session import SessionConnectOptions
# Cap de threads ONNX ANTES de cargar silero/turn_detector/wake (todos ONNX): 1 thread + sin
# spinning -> mata el ~367% CPU idle del wake (ver lk/onnx_tune.py). Debe correr antes de instanciar
# cualquier InferenceSession.
from lk.onnx_tune import cap_onnx_threads
cap_onnx_threads()
from livekit.plugins import silero, deepgram   # deepgram: import a nivel módulo (el plugin
# se registra al importar y DEBE ser en el main thread; importarlo tarde crashea)
from dotenv import load_dotenv

from lk.wakeword import WakeWordTrackDetector
from lk import speech, heard
from vc.attach import stage_text, clear_text
from vc.claudecli import prewarm_claude
from vc.config import (
    CLAUDE_SYSTEM_PROMPT, GEMINI_SYSTEM_PROMPT, SAGA_LLM, GEMINI_MODEL,
    LK_CTL_SOCK, ENV_FILE, LIVEKIT_AGENT_NAME,
    CALL_MODE, CALL_IDLE_TIMEOUT_S, FLUX_MODEL, FLUX_LANGUAGE_HINTS, FLUX_EOT_THRESHOLD,
    FLUX_EAGER_EOT_THRESHOLD, FLUX_EOT_TIMEOUT_MS, FLUX_KEYTERMS, FLUX_MIP_OPT_OUT,
    INTERRUPTION_MIN_WORDS, INTERRUPTION_MIN_DURATION, INTERRUPTION_FALSE_TIMEOUT,
)
from vc.orb import ensure_orb, orb_state
from vc.runtime import log


def _event(msg: str) -> None:
    """Evento del flujo (Win+Z / wake / silencio / estados) destacado en el monitor.
    El prefijo lo hace fácil de seguir entre el ruido de métricas."""
    log(f"  ▎ {msg}")

# Cargar secretos (DEEPGRAM_API_KEY) del .env.local gitignored. El default sólido es
# Deepgram; si NO hay key, el código cae solo a whisper/edge (no es config seteable).
load_dotenv(ENV_FILE)
_HAS_DEEPGRAM = bool(os.environ.get("DEEPGRAM_API_KEY"))
# OJO: bool("0") es True en Python -> NO usar bool() sobre el env crudo (SAGA_WAKE_ENABLED=0
# quedaba activo). Comparar el valor real.
_WAKE_ENABLED = os.environ.get("SAGA_WAKE_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")

# Voz por default (Aura-2 español, neutra). Constante, no env: arquitectura sólida.
_DEEPGRAM_VOICE = "aura-2-gloria-es"

# ¿El cerebro es Claude Code? Marca TODO el cableado que existe sólo por él: el daemon
# caliente, el turno segmentado y el transporte de la interrupción. Con un LLM en la nube
# nada de eso corre — el plugin habla el protocolo de LiveKit y el framework hace el resto.
_CEREBRO_CLAUDE = SAGA_LLM == "claude"


def _build_stt(vad):
    """STT según el modo. Sin key de Deepgram -> faster-whisper local (lento, offline).

    - modo llamada: Deepgram Flux (`STTv2`). Además de transcribir, DECIDE dónde termina
      tu turno usando señales acústicas y lingüísticas -> reemplaza el piso fijo de silencio.
    - modo push-to-talk: Nova-3 + fin de turno por VAD, que es lo que Win+Z necesita
      (el turno lo cerrás vos con la tecla o con el silencio, no el modelo).
    """
    if not _HAS_DEEPGRAM:
        from livekit.agents import stt as stt_mod
        from lk.whisper_stt import WhisperSTT
        log("[lk] STT: faster-whisper local (sin DEEPGRAM_API_KEY -> fallback lento)")
        return stt_mod.StreamAdapter(stt=WhisperSTT(), vad=vad)

    if CALL_MODE:
        hints = ",".join(FLUX_LANGUAGE_HINTS)
        log(f"[lk] STT: Deepgram Flux {FLUX_MODEL} (langs={hints}, "
            f"eot={FLUX_EOT_THRESHOLD}, eager={FLUX_EAGER_EOT_THRESHOLD})")
        return deepgram.STTv2(
            model=FLUX_MODEL,
            language_hint=FLUX_LANGUAGE_HINTS,
            eot_threshold=FLUX_EOT_THRESHOLD,
            eager_eot_threshold=FLUX_EAGER_EOT_THRESHOLD,
            eot_timeout_ms=FLUX_EOT_TIMEOUT_MS,
            # `keyterm` y no `keyterms`: el plugin marca el plural como deprecado (warning en cada
            # arranque) por consistencia con la API de Deepgram. Mismo valor, mismo efecto.
            keyterm=FLUX_KEYTERMS,
            mip_opt_out=FLUX_MIP_OPT_OUT,   # no donar el audio al programa de mejora de modelos
        )

    log("[lk] STT: Deepgram Nova-3 (streaming)")
    return deepgram.STT(model="nova-3", language="es")


def _turn_handling() -> dict:
    """Config de turnos. TODA va acá: los params top-level (min_endpointing_delay,
    preemptive_generation) están DEPRECADOS y se ignoran cuando se pasa `turn_handling`."""
    # Interrupción por VAD local (silero), NO "adaptive": ese detector se construye contra
    # LIVEKIT_INFERENCE_URL/API_KEY (LiveKit Cloud) y acá el server es local -> no se crea y la
    # sesión cae sola a `vad`. Mismo motivo por el que `backchannel_boundary` no sirve: lo aplica
    # únicamente el detector adaptativo. Ver vc/config.py, sección "interrupción".
    #
    # `resume_false_interruption`: si el VAD cree que la cortaste pero no dijiste nada (tosiste,
    # sonó algo), saga RETOMA donde iba en vez de comerse la respuesta. En una llamada, con el
    # mic siempre abierto, esto pasa seguido.
    #
    # `min_words` / `min_duration` son los dos filtros LOCALES que reemplazan lo que haría el
    # detector adaptativo: sin ellos una palabra suelta mal transcripta corta una respuesta larga
    # y fuerza un respawn de Claude (ttft 8s). Los valores y la medición, en vc/config.py.
    interruption = {
        "mode": "vad",
        "min_words": INTERRUPTION_MIN_WORDS,
        "min_duration": INTERRUPTION_MIN_DURATION,
        "resume_false_interruption": True,
        "false_interruption_timeout": INTERRUPTION_FALSE_TIMEOUT,
    }

    if CALL_MODE:
        return {
            # El fin de turno lo decide Flux (acústica + lingüística), no un umbral de silencio.
            # El VAD de la sesión sigue manejando la INTERRUPCIÓN, así que podés cortarla hablando.
            "turn_detection": "stt",
            "interruption": interruption,
            # Sigue OFF: la generación especulativa que queremos es la de Flux (`eager_eot`), que
            # cancela vía TurnResumed antes de commitear. La de LiveKit corre sobre transcripts
            # parciales y hace multi-commit contra el bridge bloqueante del daemon -> turnos
            # partidos sin respuesta (documentado en turn-flow.md). Una sola fuente de especulación.
            "preemptive_generation": {"enabled": False},
        }

    return {
        # Turn detection por VAD PURO (silero): cierra el turno por SILENCIO, no por sentido (U10).
        # Antes era el MultilingualModel (EOU semántico) -> ocupaba ~1.8 GB de RAM. En la práctica el
        # cierre ya se daba por silencio (el VAD ganaba), así que se sacó el transformer: -1.8 GB sin
        # cambio de UX perceptible. silero ya está cargado (vad=, interruption vad) -> costo cero.
        "turn_detection": "vad",
        # min_delay = silencio sin voz (silero) antes de cerrar el turno. Se paga ENTERO en
        # CADA turno, incluso en los triviales: era el 54% de la latencia percibida (3.0 de
        # 5.6s medidos). 1.2s cubre la pausa normal entre sub-frases sin partir el turno.
        # Si te corta frases a la mitad, subilo a 1.8; volver a 3.0 es tirar 2s por turno.
        "endpointing": {"min_delay": 1.2, "max_delay": 6.0},
        "interruption": interruption,
        "preemptive_generation": {"enabled": False},
    }


def _build_llm():
    """El cerebro. `SAGA_LLM=gemini` cambia a un LLM en la nube por el plugin nativo de LiveKit.

    Con Claude Code, LiveKit ve un LLM custom que adentro puentea al `claude_daemon`: de ahí
    salen el turno segmentado, el protocolo de eventos y el transporte de la interrupción
    (~1200 líneas). Con un LLM normal nada de eso hace falta — el plugin habla el protocolo
    que LiveKit espera y el framework maneja el resto solo.

    Es un MODO, no un reemplazo: se elige por env y se vuelve por env. Sirve para medir cuánta
    latencia es el modelo y cuánta el harness, con el mismo audio y el mismo orbe.
    """
    if SAGA_LLM == "gemini":
        from livekit.plugins import google
        log(f"[lk] LLM: Google {GEMINI_MODEL} (nube, SIN tools — no actúa sobre la máquina)")
        return google.LLM(model=GEMINI_MODEL)

    from lk.claude_llm import ClaudeCodeLLM   # lazy: en modo nube ni se importa
    log("[lk] LLM: Claude Code (agéntico, vía claude_daemon)")
    return ClaudeCodeLLM()


def _build_tts():
    """TTS por default = Deepgram Aura-2 (voz neutra es). Sin key -> edge-tts."""
    if _HAS_DEEPGRAM:
        log(f"[lk] TTS: Deepgram Aura-2 ({_DEEPGRAM_VOICE})")
        return deepgram.TTS(model=_DEEPGRAM_VOICE)
    from lk.edge_tts_plugin import EdgeTTS
    log("[lk] TTS: edge-tts (fallback)")
    return EdgeTTS()


# Server de control persistente (referencia global para que el loop no lo recolecte
# cuando entry() retorna; la sesión sigue viva en tasks de fondo).
_ctl_server = None

# Limpieza del socket de control al salir. Se registra en `entry()`, DESPUÉS de bindear, y NO
# acá a nivel de módulo. La diferencia no es de estilo:
#
# EL BUG (21/8, reproducido): esto era `atexit.register(...)` en el cuerpo del módulo, así que
# corría en CUALQUIER proceso que importara `lk.agent` — y LiveKit prewarmea procesos de repuesto
# que importan el módulo sin llegar a atender un job jamás. Cuando uno de esos repuestos moría, su
# atexit borraba el socket del job VIVO. Síntoma: la llamada seguía andando (el agente contestaba
# turnos) pero Win+Z tiraba `FileNotFoundError` y NO se podía colgar. Mic abierto sin forma de
# cerrarlo desde la tecla, que es justo lo que el techo de inactividad existe para evitar.
#
# Además se compara el INODO: sólo borramos el archivo que bindeamos NOSOTROS. Si otro job ya
# rebindeó el path (`entry()` hace unlink+bind al arrancar), el nuestro quedó huérfano y el que
# está en disco es de otro dueño — borrarlo repetiría el mismo bug por otro camino.
def _armar_limpieza_del_socket() -> None:
    try:
        mio = LK_CTL_SOCK.stat().st_ino
    except OSError:
        return

    def _limpiar() -> None:
        try:
            if LK_CTL_SOCK.stat().st_ino == mio:
                LK_CTL_SOCK.unlink(missing_ok=True)
        except OSError:
            pass

    atexit.register(_limpiar)


class Assistant(Agent):
    def __init__(self) -> None:
        # El system prompt real vive en el claude_daemon; ClaudeCodeLLM sólo reenvía
        # el último turno del usuario. Esto es informativo para LiveKit.
        # Con Claude Code esto es informativo: el system prompt REAL vive en el daemon
        # (`--append-system-prompt`) porque el contexto lo maneja Claude. Con un LLM en la
        # nube pasa a ser EL system prompt de verdad, y por eso cambia según el cerebro:
        # prometerle tools a un modelo que no las tiene lo hace inventar que ya actuó.
        super().__init__(instructions=GEMINI_SYSTEM_PROMPT if SAGA_LLM == "gemini"
                         else CLAUDE_SYSTEM_PROMPT)

    async def on_user_turn_completed(self, turn_ctx, new_message) -> None:
        """Hook nativo de LiveKit: corre cuando el usuario cerró su turno, con el contexto YA
        truncado y ANTES de que entre el mensaje nuevo.

        Es el único momento en que existe la información que Claude no tiene: hasta dónde llegó
        a SONAR su respuesta anterior antes de que lo interrumpieran. La guardamos acá y el
        turno la agrega al prompt. Ver lk/heard.py para el por qué.
        """
        if _CEREBRO_CLAUDE:
            heard.note_from_context(turn_ctx)


# Worker dedicado single-tenant (1 usuario, 1 room "saga"):
# - load_fnc=lambda:0.0 -> el worker NUNCA se auto-marca 'unavailable'. El default mide CPU y, en modo prod
#   (load_threshold 0.7), se excluye cuando la laptop está cargada en el arranque -> create_dispatch caía en
#   esa ventana y daba 503 ("coin-flip del dispatch"). El load-shedding es para POOLS de workers; acá hay 1
#   worker dedicado -> lo neutralizamos. (En self-hosted el load_fnc custom se respeta; sólo se ignora en Cloud.)
# - drain_timeout=0 -> al SIGTERM cierra al toque (el default 1800s dejaba el worker 'draining' ocupando :8081).
# - num_idle_processes=1 -> el prod_default es 8 (8 procesos forkeados re-importando los plugins). saga atiende
#   1 turno a la vez -> 1 proceso caliente alcanza (eficiencia: RAM + menos pico de CPU en el arranque).
# - port=0 -> que el SO asigne el puerto del health server. El prod_default es 8081 FIJO, y ese puerto es
#   tierra disputada en una laptop de trabajo (acá lo tenía un contenedor de otro proyecto -> el worker moría
#   con "address already in use" y saga no levantaba). Nadie consume ese endpoint: saga chequea readiness por
#   el socket de control, no por HTTP. Elegir otro número fijo sólo mueve la colisión de lugar.
os.environ.pop("LIVEKIT_AGENT_NAME", None)   # el nombre lo fija el código (abajo), no el shell
server = AgentServer(load_fnc=lambda: 0.0, drain_timeout=0, num_idle_processes=1, port=0)


# DISPATCH EXPLÍCITO: el worker se registra CON nombre y el orbe lo pide en su JWT
# (`RoomConfiguration.agents`, ver vc/config.LIVEKIT_AGENT_NAME y orb_server._serve_token).
#
# Antes era automático, con este comentario: "el agente entra junto con el participante -> ya no
# hay race de timing". Falso, y medido: el automático despacha al CREARSE el room, así que si la
# pestaña del orbe ya estaba abierta, el cliente reconectaba y creaba el room 2.1s antes de que el
# worker se registrara -> nadie despachaba a nadie. `saga-ctl restart` con el orbe abierto fallaba
# siempre. Con dispatch por token el agente entra cuando entra el cliente: el orden deja de importar.
@server.rtc_session(agent_name=LIVEKIT_AGENT_NAME)
async def entry(ctx: "agents.JobContext") -> None:
    global _ctl_server
    ensure_orb()       # orbe (idéntico a vc/)
    if _CEREBRO_CLAUDE:
        prewarm_claude()   # cerebro caliente en paralelo (mata el cold-start del CLI)

    # activation_threshold 0.7 (default 0.5): el mic de laptop capta ruido de fondo continuo.
    # Si el VAD lo ve como "voz", el usuario nunca pasa a 'listening' -> el user_away_timeout
    # nativo NUNCA arranca su cuenta -> el turno no cierra y el orbe queda pegado en "Grabando".
    # Subir el threshold hace que el VAD ignore el ruido -> el 'away' nativo funciona.
    vad = silero.VAD.load(activation_threshold=0.7)
    session = AgentSession(
        stt=_build_stt(vad),   # Deepgram streaming por default; whisper si no hay key
        vad=vad,
        llm=_build_llm(),
        tts=_build_tts(),      # Deepgram Aura por default; edge-tts si no hay key
        turn_handling=_turn_handling(),   # ramifica por modo (llamada vs push-to-talk)
        # (El timeout "no hablaste -> no te entendí" lo maneja un timer PROPIO abajo, VAD-aware.)
        #
        # Red de seguridad del TTS. El plugin de Deepgram hace
        # `ws.receive(timeout=conn_options.timeout)` (default 10s): si el websocket no
        # recibe audio en ese lapso, tira APITimeoutError y LiveKit NO reintenta si ya
        # mandó audio parcial -> la respuesta llega a un canal muerto y no se escucha.
        # El turno segmentado ya evita que el websocket cruce un hueco de tools; estos
        # 30s cubren el caso de un BLOQUE lento sin enmascarar un cuelgue real.
        conn_options=SessionConnectOptions(tts_conn_options=APIConnectOptions(timeout=30.0)),
    )

    # El turno segmentado necesita la session para hablar los bloques que vienen DESPUÉS
    # del primero (cuando Claude vuelve de usar tools). Ver lk/speech.py.
    if _CEREBRO_CLAUDE:
        speech.bind(session)

    # Fase del flujo (gobierna qué hace Win+Z):
    #   idle  -> nada corriendo (mic apagado)
    #   rec   -> grabando tu voz (mic abierto)
    #   busy  -> procesando: transcribiendo / pensando / hablando
    phase = {"v": "idle"}
    # ¿el turno llegó a HABLAR? Si pasó a thinking pero nunca a speaking = turno vacío (no se dijo
    # nada / sin prompt) -> mostramos 'error' (amarillo "no te entendí") en vez de volver mudo a idle.
    spoke = {"v": False}

    # Timer PROPIO de "abriste el mic y no hablaste -> no te entendí". Reemplaza el
    # user_away_timeout nativo (que obligaba a resetear con un método privado al abrir el mic).
    # VAD-aware: se ARMA al entrar en rec (Win+Z/wake) y se CANCELA apenas el VAD detecta que
    # empezaste a hablar (user_state 'speaking') o cuando el turno arranca (agent 'thinking').
    # Si vence sin que hayas hablado, vuelve a idle. Solo herramientas estándar (call_later).
    _NO_SPEECH_TIMEOUT = 6.0
    loop = asyncio.get_running_loop()
    _away = {"h": None}

    def _cancel_away() -> None:
        if _away["h"] is not None:
            _away["h"].cancel()
            _away["h"] = None

    def _arm_away() -> None:
        _cancel_away()
        _away["h"] = loop.call_later(_NO_SPEECH_TIMEOUT, _away_fire)

    def _away_fire() -> None:
        _away["h"] = None
        if phase["v"] == "rec":   # seguís en rec y nunca hablaste -> abortar
            session.input.set_audio_enabled(False)
            session.clear_user_turn()
            phase["v"] = "idle"
            orb_state("error")   # AMARILLO "No te entendí" (no el rojo de 'cancel'): es lo correcto acá
            _event(f"SILENCIO {int(_NO_SPEECH_TIMEOUT)}s sin voz -> no te entendí, vuelvo a idle")

    # Modo LLAMADA: la línea queda abierta y cuelga sola tras un rato sin actividad. No es un
    # fin de turno (eso lo decide Flux): es "no hay nadie del otro lado". Existe a propósito —
    # un mic abierto indefinidamente delante de una IA agéntica con permisos `auto` es una
    # superficie que no queremos dejar viva cuando nadie la está usando. Se rearma con CADA
    # señal de vida (voz tuya o actividad del agente).
    _call_idle = {"h": None}

    def _cancel_call_idle() -> None:
        if _call_idle["h"] is not None:
            _call_idle["h"].cancel()
            _call_idle["h"] = None

    def _arm_call_idle() -> None:
        _cancel_call_idle()
        _call_idle["h"] = loop.call_later(CALL_IDLE_TIMEOUT_S, _call_idle_fire)

    def _call_idle_fire() -> None:
        _call_idle["h"] = None
        if phase["v"] == "call":
            _hang_up(f"{int(CALL_IDLE_TIMEOUT_S)}s sin actividad -> COLGUÉ sola")

    def _hang_up(msg: str) -> None:
        """Cerrar la línea: mic abajo, respuesta en curso cortada, todo a idle."""
        _cancel_away()
        _cancel_busy()
        _cancel_call_idle()
        speech.cancel()                 # mata el drenado en background (turno segmentado)
        heard.clear()                   # colgaste: la interrupción ya no le importa a nadie
        session.interrupt(force=True)   # corta TTS + cancela el LLM (Claude)
        session.clear_user_turn()
        session.input.set_audio_enabled(False)
        phase["v"] = "idle"
        orb_state("cancel")
        _event(msg)

    # Watchdog de seguridad: si el turno queda colgado en 'busy' (thinking) SIN llegar a hablar
    # (LLM/daemon trabado, transcript que nunca llega, etc.), destraba a idle con 'no te entendí'
    # en vez de quedar pegado. Se arma al entrar a procesar, se cancela al hablar o resolver.
    # 60s: con el stack agéntico (Ciclo 5) los turnos con tool/MCP tardan 13-17s+ (tool-defs en contexto +
    # round-trips); 18s los mataba en falso. Es red de seguridad para cuelgues REALES, no presupuesto de
    # latencia. El daemon tiene su propio techo (CLAUDE_DAEMON_TURN_TIMEOUT_S=180s) que corta después.
    _PROC_TIMEOUT = 60.0
    _busy = {"h": None}

    def _cancel_busy() -> None:
        if _busy["h"] is not None:
            _busy["h"].cancel()
            _busy["h"] = None

    def _arm_busy() -> None:
        _cancel_busy()
        _busy["h"] = loop.call_later(_PROC_TIMEOUT, _busy_fire)

    def _busy_fire() -> None:
        _busy["h"] = None
        if phase["v"] == "busy" and not spoke["v"]:   # colgado procesando, nunca habló
            try: session.interrupt(force=True)
            except Exception: pass
            try: session.clear_user_turn()
            except Exception: pass
            session.input.set_audio_enabled(False)
            phase["v"] = "idle"
            orb_state("error")
            _event(f"turno colgado {int(_PROC_TIMEOUT)}s sin respuesta -> no te entendí")

    @session.on("user_state_changed")
    def _on_user_state(ev) -> None:
        # Empezaste a hablar (VAD real) -> cancelar el timeout de 'no hablaste'.
        if getattr(ev, "new_state", None) == "speaking":
            _cancel_away()
            if phase["v"] == "call":
                _arm_call_idle()   # hablaste: hay alguien del otro lado

    @session.on("agent_state_changed")
    def _on_agent_state(ev) -> None:
        st = getattr(ev, "new_state", None)
        log(f"[lk] agent_state -> {st} (phase={phase['v']})")   # DEBUG: trazar secuencia de estados

        if phase["v"] == "call":
            # LLAMADA: el mic NO se toca y la fase no cambia con cada turno. Los turnos van y
            # vienen sobre la misma línea abierta; sólo el orbe sigue al agente. Esto es lo que
            # separa una llamada de un walkie-talkie: en push-to-talk cada transición apagaba
            # el mic y volvía a idle, obligándote a apretar la tecla otra vez.
            _arm_call_idle()   # cualquier actividad cuenta como vida
            if st == "thinking":
                orb_state("think")
                _event("PENSANDO...")
            elif st == "speaking":
                orb_state("speak")
                _event("HABLANDO")
            else:   # listening / idle -> la línea sigue abierta esperándote
                orb_state("think" if speech.is_working() else "listen")
            return

        if st in ("thinking", "speaking"):
            _cancel_away()   # el turno arrancó -> ya no aplica el timeout de 'no hablaste'
            # Turno cerrado (por SILENCIO automático o por Win+Z). Si veníamos grabando,
            # el VAD cerró solo -> apagar mic y pasar a procesar.
            if phase["v"] == "rec":
                session.input.set_audio_enabled(False)
                _event("SILENCIO detectado -> fin de turno, proceso")
            if st == "thinking":
                spoke["v"] = False     # turno nuevo: todavía no respondió nada
                _arm_busy()            # watchdog: destrabar si se cuelga procesando
            else:
                spoke["v"] = True      # llegó a 'speaking' -> hubo respuesta de verdad
                _cancel_busy()
            phase["v"] = "busy"
            # 'thinking' = el STT terminó y Claude está pensando. 'speaking' = hablando.
            _event("PENSANDO..." if st == "thinking" else "HABLANDO")
            orb_state("think" if st == "thinking" else "speak")
        elif st in ("listening", "idle"):
            # Turno SEGMENTADO: el stream del LLM cerró para que el TTS no cruce el hueco,
            # pero Claude sigue usando tools. El turno NO terminó -> quedate en 'busy' con el
            # orbe en "pensando" (que es lo que realmente está pasando) hasta que el drenado
            # de lk/speech.py hable el último bloque. Win+Z sigue pudiendo matarlo.
            if speech.is_working():
                phase["v"] = "busy"
                _cancel_busy()   # el watchdog de 60s no aplica: el trabajo es legítimo y largo
                orb_state("think")
                return
            # Agente quieto. Sólo significa "terminó de responder" si estábamos ocupados;
            # si estamos grabando, el agente está "listening" esperándote -> no tocar.
            if phase["v"] == "busy":
                _cancel_busy()
                phase["v"] = "idle"
                # NOTA: acá NO mostramos "no te entendí" aunque no haya hablado. Un turno puede ir
                # thinking->listening sin speaking por CHOPPING (lo canceló un turno nuevo), no por
                # estar vacío -> mostrar error acá daba falsos positivos en frases con pausas. El
                # caso de turno REALMENTE vacío se cubre en _press (rapid Win+Z sin hablar) y en el
                # watchdog (_busy_fire) si queda colgado. Acá, simplemente volvemos a idle.
                _event("listo -> idle")
                orb_state("idle")
                spoke["v"] = False

    # Interrupción que resultó FALSA (te cortó y no dijiste nada). Es la señal para tunear
    # `min_words` / `min_duration`: muchas de estas = los filtros están flojos y saga se corta
    # sola con ruido. `resumed` dice si alcanzó a retomar donde iba o se comió la respuesta.
    @session.on("agent_false_interruption")
    def _on_false_interruption(ev) -> None:
        log(f"[lk] interrupción FALSA (retomó={getattr(ev, 'resumed', '?')})")

    # NOTA: `metrics_collected` está deprecado PARA CONTAR USO (tokens/costo) -> ahí va
    # `session_usage_updated`. Acá lo usamos para las LATENCIAS por etapa (ttft/ttfb/EOU), que es
    # con lo que se tunea todo el pipeline, y para eso el reemplazo es `ChatMessage.metrics` — que
    # vive en el chat_ctx que ClaudeCodeLLM no llena a propósito (ver lk/heard.py). Se queda hasta
    # que haya un camino que no pase por el contexto de LiveKit.
    @session.on("metrics_collected")
    def _on_metrics(ev) -> None:
        # Tiempos que emite LiveKit por etapa (para comparar latencias en el monitor).
        m = getattr(ev, "metrics", ev)
        name = type(m).__name__
        if name == "VADMetrics":   # ruido por-frame (2/s), no aporta tiempos -> ignorar
            return
        parts = [name]
        for a in ("ttft", "ttfb", "duration", "end_of_utterance_delay",
                  "transcription_delay", "audio_duration"):
            v = getattr(m, a, None)
            if isinstance(v, (int, float)):
                parts.append(f"{a}={v:.3f}s")
        log("[metrics] " + "  ".join(parts))

    # Ruido: en room nos apoyamos en el VAD Silero (activation_threshold 0.7). BVC (noise_cancellation)
    # NO aplica self-hosted (requiere LiveKit Cloud: "audio filter cannot be enabled") -> no se usa.
    # close_on_disconnect=False: al recargar/cerrar la pestaña del orbe, la sesión (y el job) NO se cierran
    # -> el socket de control de Win+Z (creado en este entry) SOBREVIVE -> al reconectar el browser sigue
    # andando. Con el default (True) el job moría con el browser y Win+Z daba ConnectionRefusedError.
    # Los demás campos de RoomOptions quedan en su default (idéntico a no pasarlo): no toca el pipeline.
    await session.start(agent=Assistant(), room=ctx.room,
                        room_options=RoomOptions(close_on_disconnect=False))

    # Arrancar con el mic APAGADO: el agente NO escucha hasta que apretás Win+Z.
    session.input.set_audio_enabled(False)
    orb_state("idle")
    log("[lk] transporte: room (track del browser)")
    if CALL_MODE:
        log(f"[lk] modo LLAMADA. Win+Z: abre la línea / cuelga. Los turnos los corta Flux "
            f"(eot={FLUX_EOT_THRESHOLD}, eager={FLUX_EAGER_EOT_THRESHOLD}). "
            f"Cuelga sola tras {int(CALL_IDLE_TIMEOUT_S)}s sin actividad.")
    else:
        log("[lk] modo PUSH-TO-TALK. Win+Z: graba / corta y manda / mata. Silencio 2s también manda.")

    # ── Win+Z (un solo comando "press"): el agente decide según la fase ──
    def _press() -> None:
        p = phase["v"]
        if CALL_MODE:
            # LLAMADA: Win+Z levanta el tubo o cuelga. No existe "grabar un turno" — la línea
            # queda abierta y el fin de cada turno lo decide Flux (acústica + lingüística).
            if p == "idle":
                session.clear_user_turn()
                session.input.set_audio_enabled(True)
                phase["v"] = "call"
                orb_state("listen")
                _arm_call_idle()
                _event(f"Win+Z -> LLAMADA ABIERTA (hablá cuando quieras; "
                       f"cuelga sola tras {int(CALL_IDLE_TIMEOUT_S)}s sin actividad)")
            else:
                _hang_up("Win+Z -> COLGUÉ")
            return

        if p == "idle":
            # Empezar a grabar.
            session.clear_user_turn()
            session.input.set_audio_enabled(True)
            phase["v"] = "rec"
            orb_state("rec")           # "● Grabando"
            _arm_away()                # arranca el timeout 'abriste el mic y no hablaste' (6s frescos)
            _event("Win+Z -> GRABANDO (hablá)")
        elif p == "rec":
            # ¿Hablaste? El away timer se cancela al detectar voz (user_state 'speaking'). Si SIGUE
            # armado, nunca hablaste -> cortar fue un turno VACÍO: no mandar nada, mostrar 'no te
            # entendí' al toque (evita el cuelgue de comitear un turno sin transcript).
            never_spoke = _away["h"] is not None
            _cancel_away()
            session.input.set_audio_enabled(False)
            if never_spoke:
                session.clear_user_turn()
                phase["v"] = "idle"
                orb_state("error")
                _event("Win+Z -> cortaste sin hablar -> no te entendí")
            else:
                # Cortar y MANDAR el turno ya (sin esperar el silencio).
                phase["v"] = "busy"
                orb_state("think")   # STT (Deepgram) es instantáneo -> directo a Pensando
                session.commit_user_turn(transcript_timeout=10.0)
                _event("Win+Z -> CORTÉ, mando el turno")
        else:  # busy
            # Matar la respuesta/proceso en curso y volver a idle (con animación cancel).
            _cancel_away()
            _cancel_busy()
            speech.cancel()                 # mata el drenado en background (turno segmentado)
            session.interrupt(force=True)   # corta TTS + cancela el LLM (Claude)
            session.clear_user_turn()
            session.input.set_audio_enabled(False)
            phase["v"] = "idle"
            orb_state("cancel")             # animación de cancelado -> vuelve a idle solo
            _event("Win+Z -> CANCELADO (maté la respuesta)")

    def _say(text: str) -> None:
        """Prompt directo por TEXTO (Shift+Enter en el panel del orbe): dispara un turno
        inmediato sin grabar voz. Pasa por el MISMO LLM (ClaudeCodeLLM) + TTS -> responde por
        voz. La imagen pegada (si hay) se incluye vía take_staged() dentro del LLM."""
        clear_text()   # el texto ya viaja en `text` (user_input) -> descartá el staged, no dupliques
        _cancel_away()
        if phase["v"] == "rec":
            session.input.set_audio_enabled(False)   # estabas grabando -> cancelá el mic
        elif phase["v"] == "busy":
            speech.cancel()                          # cortá el drenado del turno anterior
            session.interrupt(force=True)            # respuesta en curso -> cortala y reemplazá
        phase["v"] = "busy"
        orb_state("think")
        session.generate_reply(user_input=text)      # user_input -> ClaudeCodeLLM lee el último turno
        _event("Texto (Shift+Enter) -> turno inmediato")

    async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            data = await asyncio.wait_for(reader.readline(), timeout=2.0)
            raw = data.decode("utf-8", "replace").strip()
            cmd, _, arg = raw.partition(" ")    # "say <b64>" -> no lowercasear el payload
            cmd = cmd.lower()
            if cmd in ("press", "toggle"):   # Win+Z -> una acción según la fase
                _press()
                writer.write(b"ok\n")
            elif cmd == "stage":             # texto del textarea (autosave) -> staged en memoria
                try:
                    text = base64.b64decode(arg.encode("ascii")).decode("utf-8", "replace")
                except (ValueError, UnicodeDecodeError):
                    text = ""
                stage_text(text)             # vacío -> limpia el staged
                writer.write(b"ok\n")
            elif cmd == "say":               # prompt por texto -> turno inmediato
                try:
                    text = base64.b64decode(arg.encode("ascii")).decode("utf-8", "replace").strip()
                except (ValueError, UnicodeDecodeError):
                    text = ""
                if text:
                    _say(text)
                    writer.write(b"ok\n")
                else:
                    writer.write(b"err\n")
            else:
                writer.write(b"err\n")
            await writer.drain()
        except (asyncio.TimeoutError, OSError):
            pass
        finally:
            try:
                writer.close()
            except OSError:
                pass

    try:
        LK_CTL_SOCK.unlink(missing_ok=True)   # limpiar socket viejo (start_unix_server falla si existe)
    except OSError:
        pass
    _ctl_server = await asyncio.start_unix_server(_handle, path=str(LK_CTL_SOCK))
    try:
        os.chmod(str(LK_CTL_SOCK), 0o600)     # privado al usuario (como los otros sockets del proyecto)
    except OSError:
        pass
    # Recién ACÁ, con el socket bindeado por ESTE proceso, se arma la limpieza al salir. Ver el
    # comentario de `_armar_limpieza_del_socket`: a nivel de módulo se lo llevaban los prewarm.
    _armar_limpieza_del_socket()

    # Wake word server-side (opt-in: SAGA_WAKE_ENABLED=1). Al detectar "hey saga" -> _press()
    # (mismo flujo que Win+Z). Corre sobre el track del mic del BROWSER -> WakeWordTrackDetector (U4).
    # El worker es headless; el browser publica el mic DESMUTEADO (orb.html lee el flag `wake` del
    # /token). El STT sigue gateado por set_audio_enabled -> solo procesa tras el wake; el detector lee
    # el track directo (independiente de set_audio_enabled) -> oye siempre.
    _wake_track = {"d": None}   # un solo detector aunque lleguen varios track_subscribed
    if _WAKE_ENABLED:
        log("[lk] wake server-side ON: esperando el track del mic del browser.")

        def _on_wake() -> None:
            """"hey saga" = QUIERO HABLARTE. Nunca "colgá".

            El wake compartía callback con Win+Z, y en modo llamada un `press` con la línea
            abierta es COLGAR: un disparo del wake mataba la conversación en curso. Con el
            umbral bajo eso pasa con ruido de fondo — visto en un E2E, confianza 0.11 cortó
            la llamada a los 4 segundos. La tecla puede significar las dos cosas porque la
            apretás a propósito; el wake, no.
            """
            if phase["v"] == "call":
                log("[wakeword] ya estás en llamada -> ignoro (el wake no cuelga)")
                return
            _press()

        def _start_wake_on_track(track) -> None:
            if _wake_track["d"] is not None:
                return
            det = WakeWordTrackDetector(track=track, on_wake=_on_wake)
            _wake_track["d"] = det
            asyncio.create_task(det.start())

        def _on_track_subscribed(track, publication, participant) -> None:
            # Solo el mic del browser (no el TTS que publica el worker ni otros tracks).
            if (track.kind == rtc.TrackKind.KIND_AUDIO
                    and publication.source == rtc.TrackSource.SOURCE_MICROPHONE):
                _start_wake_on_track(track)

        ctx.room.on("track_subscribed", _on_track_subscribed)
        # El mic puede haberse suscrito ANTES de registrar el handler (timing del dispatch):
        # barrer los tracks ya presentes.
        for p in ctx.room.remote_participants.values():
            for pub in p.track_publications.values():
                if (pub.track and pub.track.kind == rtc.TrackKind.KIND_AUDIO
                        and pub.source == rtc.TrackSource.SOURCE_MICROPHONE):
                    _start_wake_on_track(pub.track)


if __name__ == "__main__":
    agents.cli.run_app(server)
