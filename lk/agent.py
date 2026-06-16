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

Correr local, sin servidor ni cuenta:
    .venv/bin/python lk/agent.py console
"""

import os
import sys
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
from vc.claudecli import prewarm_claude
from vc.config import CLAUDE_SYSTEM_PROMPT, LK_CTL_SOCK, ENV_FILE
from vc.orb import ensure_orb, orb_state
from vc.runtime import log

# Cargar secretos (DEEPGRAM_API_KEY) del .env.local gitignored. El default sólido es
# Deepgram; si NO hay key, el código cae solo a whisper/edge (no es config seteable).
load_dotenv(ENV_FILE)
_HAS_DEEPGRAM = bool(os.environ.get("DEEPGRAM_API_KEY"))

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


@server.rtc_session()
async def entry(ctx: "agents.JobContext") -> None:
    global _ctl_server
    ensure_orb()       # orbe (idéntico a vc/)
    prewarm_claude()   # cerebro caliente en paralelo

    vad = silero.VAD.load()
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
    )

    # Fase del flujo (gobierna qué hace Win+Z, igual que el flujo clásico):
    #   idle  -> nada corriendo (mic apagado)
    #   rec   -> grabando tu voz (mic abierto)
    #   busy  -> procesando: transcribiendo / pensando / hablando
    phase = {"v": "idle"}

    @session.on("agent_state_changed")
    def _on_agent_state(ev) -> None:
        st = getattr(ev, "new_state", None)
        if st in ("thinking", "speaking"):
            # Turno cerrado (por SILENCIO automático o por Win+Z). Si veníamos grabando,
            # el VAD cerró solo -> apagar mic y pasar a procesar.
            if phase["v"] == "rec":
                session.input.set_audio_enabled(False)
                log("[lk] silencio -> fin de turno, procesando")
            phase["v"] = "busy"
            # 'thinking' = Whisper ya terminó y Claude está pensando. 'speaking' = hablando.
            orb_state("think" if st == "thinking" else "speak")
        elif st in ("listening", "idle"):
            # Agente quieto. Sólo significa "terminó de responder" si estábamos ocupados;
            # si estamos grabando, el agente está "listening" esperándote -> no tocar.
            if phase["v"] == "busy":
                phase["v"] = "idle"
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
    # fondo (guitarra, música, otra gente) ANTES del VAD/STT -> el corte por silencio
    # deja de dispararse con sonido ambiente. Si no carga, sigue sin cancelación.
    try:
        _nc = noise_cancellation.BVC()
    except Exception as e:  # noqa: BLE001
        log(f"[lk] noise cancellation OFF ({type(e).__name__})")
        _nc = None
    await session.start(
        agent=Assistant(),
        room=ctx.room,
        room_input_options=room_io.RoomInputOptions(noise_cancellation=_nc),
    )

    # Arrancar con el mic APAGADO: el agente NO escucha hasta que apretás Win+Z.
    session.input.set_audio_enabled(False)
    orb_state("idle")
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
            log("[lk] Win+Z -> grabar")
        elif p == "rec":
            # Cortar y MANDAR el turno ya (sin esperar el silencio).
            session.input.set_audio_enabled(False)
            phase["v"] = "busy"
            orb_state("think")   # STT (Deepgram) es instantáneo -> directo a Pensando
            session.commit_user_turn(transcript_timeout=10.0)
            log("[lk] Win+Z -> cortar y mandar")
        else:  # busy
            # Matar la respuesta/proceso en curso y volver a idle (con animación cancel).
            session.interrupt(force=True)   # corta TTS + cancela el LLM (Claude)
            session.clear_user_turn()
            session.input.set_audio_enabled(False)
            phase["v"] = "idle"
            orb_state("cancel")             # animación de cancelado -> vuelve a idle solo
            log("[lk] Win+Z -> matar (cancelado)")

    async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            data = await asyncio.wait_for(reader.readline(), timeout=2.0)
            cmd = data.decode("utf-8", "replace").strip().lower()
            if cmd in ("press", "toggle"):   # Win+Z -> una acción según la fase
                _press()
                writer.write(b"ok\n")
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


if __name__ == "__main__":
    agents.cli.run_app(server)
