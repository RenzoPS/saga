# lk/ — modo LiveKit (default)

Agente de voz sobre **LiveKit Agents**. LiveKit es dueño del runtime de audio (captura,
streaming, chunks, VAD, fin-de-turno, barge-in). Nosotros enchufamos STT/cerebro/TTS.
Default actual (Ciclo 4): **modo ROOM** — worker headless conectado a un livekit-server
nativo local; el audio entra/sale por el track del browser (cliente orbe). Ver el
`README.md` de la raíz para el panorama completo.

## Piezas
- `agent.py` — entrypoint. `AgentServer` + `AgentSession` (STT/LLM/TTS) + máquina de 3 fases Win+Z + socket de control + orbe.
- `claude_llm.py` — LLM custom: delega en `claude_daemon` (cerebro) y dispara visión (grim) en comandos visuales. Cancela el turno del daemon en barge-in/interrupción (sin zombie).
- `whisper_stt.py` — STT de fallback (faster-whisper local) si no hay `DEEPGRAM_API_KEY`.
- `edge_tts_plugin.py` — TTS de fallback (edge-tts) si no hay key.

## Stack por default (si hay DEEPGRAM_API_KEY)
- STT: `deepgram.STT("nova-3", language="es")` — streaming.
- TTS: `deepgram.TTS("aura-2-gloria-es")` — voz española neutra (constante `_DEEPGRAM_VOICE`).
- VAD: `silero.VAD.load(activation_threshold=0.7)` — sube el piso para que el mic de laptop ignore ruido de fondo.
- Fin de turno: **VAD puro** (silero, `activation_threshold 0.7`, `turn_detection="vad"`). El turno cierra por SILENCIO. (Antes era un turn detector semántico `MultilingualModel` que cerraba por el SENTIDO de la frase; U10 lo reemplazó por VAD puro → liberó ~1.8 GB de RAM y sacó el error "Error predicting end of turn".)
- Ruido: en room se apoya en el VAD Silero (activation_threshold 0.7). BVC (`noise_cancellation`) NO se usa: requiere LiveKit Cloud y falla al aplicarse contra el server self-hosted.

### Config de turnos (`turn_handling`)
TODA la config de turnos va DENTRO del dict `turn_handling` de `AgentSession`. Los params
top-level (`preemptive_generation`, `min_endpointing_delay`, …) están **deprecados y se
ignoran** cuando se pasa `turn_handling`.
- `turn_detection`: `"vad"` — fin de turno por el VAD silero (cierre por silencio). (Antes `MultilingualModel()`, EOU semántico; U10 lo pasó a VAD puro → −1.8 GB de RAM.)
- `endpointing`: `{"min_delay": 3.0, "max_delay": 6.0}` — piso de ~3s de silencio antes de cerrar (deja seguir hablando entre sub-frases).
- `interruption`: `{"mode": "vad"}` — barge-in por VAD local (silero), NO `adaptive` (el default necesita LiveKit Cloud).
- `preemptive_generation`: `{"enabled": False}` — apagado a propósito. El default (`enabled: True`) arranca el LLM sobre transcripts parciales y los cancela/reintenta; con el LLM custom (bridge bloqueante al `claude_daemon`) eso causa multi-commit → turnos partidos sin respuesta. **DENTRO** de `turn_handling` (el top-level no tenía efecto).

## Correr
```bash
saga-ctl start                            # recomendado (lanza el worker fresco + monitor; el dispatch lo dispara el browser)
.venv/bin/python lk/agent.py start        # room directo (usa LIVEKIT_URL/API_KEY/API_SECRET de .env.local)
```

### Transporte: ROOM (único)
Worker headless conectado al livekit-server local. El audio entra por el track del BROWSER (cliente orbe) y el TTS sale por el mismo room. El track detached DESCARTA frames → sin backlog. El wake (opt-in `SAGA_WAKE_ENABLED=1`, U4) corre en el SERVER sobre el track del mic (`WakeWordTrackDetector`), reusando el modelo Python.

### Dispatch AUTOMÁTICO (room, U8)
El worker se registra con dispatch nativo: `@server.rtc_session()` **SIN** `agent_name`, sobre un
`AgentServer(load_fnc=lambda: 0.0, drain_timeout=0, num_idle_processes=1)`. Cuando el browser se une al room
"saga", lo crea y el server despacha el worker solo → `entry()` → socket de control. **No** se despacha por
API (se eliminó `_ensure_agent_dispatched` de `vcctl` y `LIVEKIT_AGENT_NAME` de `vc/config`); `lk/agent.py`
hace `os.environ.pop("LIVEKIT_AGENT_NAME", None)` antes de crear el server (esa env forzaría explicit
dispatch). `load_fnc=0` → el worker nunca se auto-marca `unavailable`: esa era la causa raíz del Win+Z
`FileNotFoundError` intermitente (el prod `load_threshold=0.7` shedeaba bajo la carga de arranque →
load-shedding de pools sobre un worker single-tenant), NO pestañas zombie ni un "server envenenado".
`drain_timeout=0` → SIGTERM cierra al toque (libera el :8081, antes "draining" lo ocupaba). El worker corre
con `session.start(..., room_input_options=RoomInputOptions(close_on_disconnect=False))` → recargar/cerrar la
pestaña del orbe NO mata la sesión ni el socket de Win+Z.

## Win+Z (3 fases, vía socket de control LK_CTL_SOCK)
Máquina de 3 fases (`idle`/`rec`/`busy`): idle→graba · rec→corta y manda (`commit_user_turn`) ·
busy→mata la respuesta en curso (`interrupt(force=True)` + cancela el LLM). Silencio (VAD silero
+ ~3s) también cierra y manda. Win+Z (otro proceso) manda `press` al socket Unix;
el server del socket corre en el MISMO loop que la sesión → llama la API de LiveKit directo.

### Timers PROPIOS (no internals privados)
Implementados con `asyncio.call_later` (herramientas estándar), reemplazan los timeouts nativos:
- **away** (`_NO_SPEECH_TIMEOUT` 6s): se arma al abrir el mic (rec) y se cancela apenas el VAD detecta voz. Si vence sin hablar → vuelve a idle con orbe **amarillo "no te entendí"** (empty-cut, no el rojo de cancel).
- **busy/watchdog** (`_PROC_TIMEOUT` 60s): se arma al entrar a procesar; si el turno queda colgado en `thinking` sin llegar a `speaking`, destraba a idle con "no te entendí". (Era 18s; subido en Ciclo 5 porque los turnos con tool/MCP tardan 13-17s+ y 18s los mataba en falso.)

## Otros endpoints del panel (orb_server → socket)
- `say` (Shift+Enter): prompt por TEXTO → `session.generate_reply(user_input=…)` → mismo LLM+TTS, sin grabar voz.
- `stage`: texto del textarea (autosave) → staged en memoria del agente (`vc/attach`), consumido en el turno.

## Orbe sincronizado (U5)
El cliente browser sincroniza el orbe con la **voz real**: Web Audio `AnalyserNode`
sobre el track TTS remoto → nivel RMS en vivo. El estado (idle/think/speak/…) sigue
llegando por SSE desde `orb_server`.

## Notas
- Los plugins (deepgram/silero/noise-cancellation/turn-detector) se importan a NIVEL MÓDULO (se registran en el main thread; importarlos tarde crashea).
- **Cap de threads ONNX (U9, `lk/onnx_tune.py`)**: `cap_onnx_threads()` se llama en `agent.py` antes de cargar los modelos. ONNX por default usa 1 thread/core + spinning → el wake quemaba ~367% CPU idle. Con intra/inter=1 + `allow_spinning=0` el worker bajó de ~410% a ~40% sin perder detección. NO sacarlo.
- La key se carga de `.env.local` con `python-dotenv` al importar el módulo.
- Sin `DEEPGRAM_API_KEY` → cae solo a whisper/edge (no es config, lo decide la presencia de la key).
