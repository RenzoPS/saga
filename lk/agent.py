"""Entrypoint del modo LiveKit (push-to-talk).

LiveKit-agents es dueño del runtime de audio: captura, streaming, chunks, VAD,
barge-in. Nosotros enchufamos las piezas:
  - STT  -> Deepgram Nova-3 streaming (default); whisper local si no hay key.
  - LLM  -> Claude Code (vía claude_daemon).
  - TTS  -> Deepgram Aura-2 voz es (default); edge-tts si no hay key.
La elección la decide la presencia de DEEPGRAM_API_KEY (.env.local), NO un flag.

Fin de turno por SILENCIO (turn_detection="vad", ~2s). Win+Z es una máquina de 3
fases (como el flujo clásico):
  - idle -> graba (mic ON)
  - rec  -> corta y manda el turno (commit_user_turn)
  - busy -> mata la respuesta en curso (interrupt) y vuelve a idle
Win+Z (otro proceso) habla con el agente por un socket Unix (LK_CTL_SOCK) mandando
"press"; el server del socket corre en el MISMO loop que la sesión -> llama la API
de LiveKit directo.

Dos modos de transporte (mismo código; el subcomando decide):
  - ROOM (default, Ciclo 4): worker conectado a livekit-server. El audio llega por el
    track del BROWSER (cliente orbe). En room el track detached DESCARTA frames
    (room_io/_input.py) -> NO hay backlog (resuelve el bug del modo console). El wake
    corre en el CLIENTE (onnxruntime-web, U4), no acá: el worker es headless.
        .venv/bin/python lk/agent.py start      # usa LIVEKIT_URL/API_KEY/API_SECRET (.env.local)
  - CONSOLE (fallback dev): runtime de audio local, sin server. El wake server-side
    (mic local) SÍ corre acá. Tiene el bug del buffer conocido (ver Ciclo 3).
        .venv/bin/python lk/agent.py console
"""

import os
import sys
import base64
import asyncio

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from livekit import agents
from livekit.agents import AgentServer, AgentSession, Agent, room_io
from livekit.plugins import silero, deepgram   # deepgram: import a nivel módulo (el plugin
# se registra al importar y DEBE ser en el main thread; importarlo tarde crashea)
from livekit.plugins import noise_cancellation   # BVC: saca ruido + voces de fondo del mic
from dotenv import load_dotenv

from lk.claude_llm import ClaudeCodeLLM
from lk.wakeword import WakeWordDetector
from vc.attach import stage_text, clear_text
from vc.claudecli import prewarm_claude
from vc.config import CLAUDE_SYSTEM_PROMPT, LK_CTL_SOCK, ENV_FILE, LIVEKIT_AGENT_NAME
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
# Modo de transporte = el subcomando con el que se lanza. `console` -> audio local (fallback);
# cualquier otro (`start`/`dev`) -> room (worker conectado al server, default Ciclo 4).
_CONSOLE_MODE = "console" in sys.argv

# Voz por default (Aura-2 español, neutra). Constante, no env: arquitectura sólida.
_DEEPGRAM_VOICE = "aura-2-gloria-es"


def _build_stt(vad):
    """STT por default = Deepgram Nova-3 streaming (rápido, preciso). Sin key -> cae
    a faster-whisper local (lento, pero anda offline). No hay flag: lo decide la key."""
    if _HAS_DEEPGRAM:
        log("[lk] STT: Deepgram Nova-3 (streaming)")
        return deepgram.STT(model="nova-3", language="es")
    from livekit.agents import stt as stt_mod
    from lk.whisper_stt import WhisperSTT
    log("[lk] STT: faster-whisper local (sin DEEPGRAM_API_KEY -> fallback lento)")
    return stt_mod.StreamAdapter(stt=WhisperSTT(), vad=vad)


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


class Assistant(Agent):
    def __init__(self) -> None:
        # El system prompt real vive en el claude_daemon; ClaudeCodeLLM sólo reenvía
        # el último turno del usuario. Esto es informativo para LiveKit.
        super().__init__(instructions=CLAUDE_SYSTEM_PROMPT)


server = AgentServer()


# agent_name -> el worker se registra como agente NOMBRADO (no auto-dispatch). Se despacha solo
# cuando el token del cliente lo pide explícitamente (ver /token en orb_server). Robustece el
# dispatch contra el orden de arranque / pestañas zombie. En console (sin server) se ignora.
@server.rtc_session(agent_name=LIVEKIT_AGENT_NAME)
async def entry(ctx: "agents.JobContext") -> None:
    global _ctl_server
    ensure_orb()       # orbe (idéntico a vc/)
    prewarm_claude()   # cerebro caliente en paralelo

    # activation_threshold 0.7 (default 0.5): el mic de laptop capta ruido de fondo continuo.
    # Si el VAD lo ve como "voz", el usuario nunca pasa a 'listening' -> el user_away_timeout
    # nativo NUNCA arranca su cuenta -> el turno no cierra y el orbe queda pegado en "Grabando".
    # Subir el threshold hace que el VAD ignore el ruido -> el 'away' nativo funciona.
    vad = silero.VAD.load(activation_threshold=0.7)
    session = AgentSession(
        stt=_build_stt(vad),   # Deepgram streaming por default; whisper si no hay key
        vad=vad,
        llm=ClaudeCodeLLM(),
        tts=_build_tts(),      # Deepgram Aura por default; edge-tts si no hay key
        # Fin de turno por SILENCIO (VAD): ~2s de silencio cierra el turno y manda el
        # prompt (como el flujo clásico). Sin esperar al modelo lingüístico.
        turn_handling={
            "turn_detection": "vad",
            "endpointing": {"min_delay": 2.0, "max_delay": 4.0},
            # Interrupción por VAD local (silero), NO "adaptive" (que es el default y
            # necesita LIVEKIT_API_KEY de la nube -> sin key fallaba al crear el detector
            # y rompía todo al apretar Win+Z mientras hablaba). vad = local, sin key.
            "interruption": {"mode": "vad"},
        },
        # Si grabás y NO hablás en 6s, LiveKit marca al usuario "away" (mecanismo nativo,
        # basado en VAD real). Lo enganchamos abajo para volver a idle ('no entendí').
        user_away_timeout=6.0,
    )

    # Fase del flujo (gobierna qué hace Win+Z, igual que el flujo clásico):
    #   idle  -> nada corriendo (mic apagado)
    #   rec   -> grabando tu voz (mic abierto)
    #   busy  -> procesando: transcribiendo / pensando / hablando
    phase = {"v": "idle"}

    @session.on("user_state_changed")
    def _on_user_state(ev) -> None:
        # "away" = LiveKit no detectó voz por user_away_timeout (6s) desde que abrió el mic.
        # Si seguíamos grabando sin que nadie hablara -> abortar y volver a idle ('no entendí').
        # Mecanismo nativo basado en VAD real (no un timer ciego) -> sin races.
        if getattr(ev, "new_state", None) == "away" and phase["v"] == "rec":
            session.input.set_audio_enabled(False)
            session.clear_user_turn()
            phase["v"] = "idle"
            orb_state("cancel")
            _event("SILENCIO 6s sin voz -> no te entendí, vuelvo a idle")

    @session.on("agent_state_changed")
    def _on_agent_state(ev) -> None:
        st = getattr(ev, "new_state", None)
        log(f"[lk] agent_state -> {st} (phase={phase['v']})")   # DEBUG: trazar secuencia de estados
        if st in ("thinking", "speaking"):
            # Turno cerrado (por SILENCIO automático o por Win+Z). Si veníamos grabando,
            # el VAD cerró solo -> apagar mic y pasar a procesar.
            if phase["v"] == "rec":
                session.input.set_audio_enabled(False)
                _event("SILENCIO detectado -> fin de turno, proceso")
            phase["v"] = "busy"
            # 'thinking' = el STT terminó y Claude está pensando. 'speaking' = hablando.
            _event("PENSANDO..." if st == "thinking" else "HABLANDO")
            orb_state("think" if st == "thinking" else "speak")
        elif st in ("listening", "idle"):
            # Agente quieto. Sólo significa "terminó de responder" si estábamos ocupados;
            # si estamos grabando, el agente está "listening" esperándote -> no tocar.
            if phase["v"] == "busy":
                phase["v"] = "idle"
                _event("listo -> idle")
                orb_state("idle")

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

    # Cancelación de ruido en el INPUT (BVC = Krisp): saca ruido y voces/sonidos de
    # fondo ANTES del VAD/STT. OJO: BVC necesita LiveKit Cloud -> en el server self-hosted
    # (modo room) NO se puede habilitar ("audio filter cannot be enabled: LiveKit Cloud is
    # required") y ensucia el pipeline. Solo en console. En room nos apoyamos en el VAD Silero
    # (activation_threshold 0.7) para el ruido. BVC()=construye OK pero falla al APLICARSE ->
    # por eso se gatea por modo, no por try/except.
    _nc = None
    if _CONSOLE_MODE:
        try:
            _nc = noise_cancellation.BVC()
        except Exception as e:  # noqa: BLE001
            log(f"[lk] noise cancellation OFF ({type(e).__name__})")
            _nc = None
    await session.start(
        agent=Assistant(),
        room=ctx.room,
        # API actual de livekit-agents 1.6 (RoomInputOptions/RoomOutputOptions están deprecados):
        # noise_cancellation vive ahora en RoomOptions.audio_input.
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(noise_cancellation=_nc),
        ),
    )

    # Arrancar con el mic APAGADO: el agente NO escucha hasta que apretás Win+Z.
    session.input.set_audio_enabled(False)
    orb_state("idle")
    log(f"[lk] transporte: {'console (audio local)' if _CONSOLE_MODE else 'room (track del browser)'}")
    log("[lk] agente listo. Win+Z: graba / corta y manda / mata. Silencio 2s también manda.")

    # ── Win+Z (un solo comando "press"): el agente decide según la fase ──
    def _press() -> None:
        p = phase["v"]
        if p == "idle":
            # Empezar a grabar.
            session.clear_user_turn()
            session.input.set_audio_enabled(True)
            phase["v"] = "rec"
            orb_state("rec")           # "● Grabando"
            _event("Win+Z -> GRABANDO (hablá)")
        elif p == "rec":
            # Cortar y MANDAR el turno ya (sin esperar el silencio).
            session.input.set_audio_enabled(False)
            phase["v"] = "busy"
            orb_state("think")   # STT (Deepgram) es instantáneo -> directo a Pensando
            session.commit_user_turn(transcript_timeout=10.0)
            _event("Win+Z -> CORTÉ, mando el turno")
        else:  # busy
            # Matar la respuesta/proceso en curso y volver a idle (con animación cancel).
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
        if phase["v"] == "rec":
            session.input.set_audio_enabled(False)   # estabas grabando -> cancelá el mic
        elif phase["v"] == "busy":
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

    # Wake word server-side (opt-in: SAGA_WAKE_ENABLED=1) — SOLO en console. Abre el mic
    # LOCAL del proceso (listener portaudio); en room el worker es headless (el audio llega
    # por el track del browser), así que el wake corre en el CLIENTE (onnxruntime-web, U4).
    # Al detectar "hey saga" llama _press() -> mismo flujo que Win+Z.
    if _WAKE_ENABLED and _CONSOLE_MODE:
        _wake = WakeWordDetector(on_wake=_press)
        await _wake.start()
    elif _WAKE_ENABLED:
        log("[lk] wake server-side OFF en modo room (corre en el cliente, U4).")


if __name__ == "__main__":
    agents.cli.run_app(server)
