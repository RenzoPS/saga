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
- Fin de turno: turn detector **SEMÁNTICO** `MultilingualModel` (livekit-plugins-turn-detector), no solo silencio. Cierra el turno por el SENTIDO de la frase → anti-chopping en frases con pausas.
- Ruido (BVC `noise_cancellation`): **solo en console** (requiere LiveKit Cloud). En room se apoya en el VAD Silero; intentar habilitar BVC contra el server self-hosted falla al aplicarse, por eso se gatea por modo.

### Config de turnos (`turn_handling`)
TODA la config de turnos va DENTRO del dict `turn_handling` de `AgentSession`. Los params
top-level (`preemptive_generation`, `min_endpointing_delay`, …) están **deprecados y se
ignoran** cuando se pasa `turn_handling`.
- `turn_detection`: `MultilingualModel()` (EOU semántico multilingüe, soporta español).
- `endpointing`: `{"min_delay": 2.0, "max_delay": 6.0}` — piso de ~2s de silencio antes de cerrar (deja seguir hablando entre sub-frases).
- `interruption`: `{"mode": "vad"}` — barge-in por VAD local (silero), NO `adaptive` (el default necesita LiveKit Cloud).
- `preemptive_generation`: `{"enabled": False}` — apagado a propósito. El default (`enabled: True`) arranca el LLM sobre transcripts parciales y los cancela/reintenta; con el LLM custom (bridge bloqueante al `claude_daemon`) eso causa multi-commit → turnos partidos sin respuesta. **DENTRO** de `turn_handling` (el top-level no tenía efecto).

## Correr
```bash
saga-ctl start                            # recomendado (lanza el worker + monitor + crea el dispatch)
.venv/bin/python lk/agent.py start        # room directo (usa LIVEKIT_URL/API_KEY/API_SECRET de .env.local)
.venv/bin/python lk/agent.py console      # fallback dev: audio local, sin servidor
```

### Transporte: ROOM (default) vs CONSOLE (fallback)
El modo lo decide el **subcomando**, no un flag:
- **`start`/`dev` → ROOM** (default, Ciclo 4): worker headless conectado al livekit-server local. El audio entra por el track del BROWSER (cliente orbe) y el TTS sale por el mismo room. El track detached DESCARTA frames → sin backlog (resuelve el bug del buffer del modo console). El wake corre en el CLIENTE (onnxruntime-web, U4); el worker no escucha mic local.
- **`console` → CONSOLE** (fallback dev): runtime de audio local del proceso, sin server. El wake server-side (mic local, opt-in `SAGA_WAKE_ENABLED=1`) SÍ corre acá. Tiene el bug del buffer conocido (Ciclo 3).

### Dispatch EXPLÍCITO (room)
El worker se registra como agente NOMBRADO: `@server.rtc_session(agent_name="saga")`
(`LIVEKIT_AGENT_NAME`). **No** hay auto-dispatch: `saga-ctl`/`vcctl` hace
`create_dispatch` (CreateAgentDispatchRequest) para asignar el agente al room. Robustece
contra el orden de arranque y pestañas zombie. En console (sin server) se ignora.

## Win+Z (3 fases, vía socket de control LK_CTL_SOCK)
Máquina de 3 fases (`idle`/`rec`/`busy`): idle→graba · rec→corta y manda (`commit_user_turn`) ·
busy→mata la respuesta en curso (`interrupt(force=True)` + cancela el LLM). Silencio (turn
detector + ~2s) también cierra y manda. Win+Z (otro proceso) manda `press` al socket Unix;
el server del socket corre en el MISMO loop que la sesión → llama la API de LiveKit directo.

### Timers PROPIOS (no internals privados)
Implementados con `asyncio.call_later` (herramientas estándar), reemplazan los timeouts nativos:
- **away** (`_NO_SPEECH_TIMEOUT` 6s): se arma al abrir el mic (rec) y se cancela apenas el VAD detecta voz. Si vence sin hablar → vuelve a idle con orbe **amarillo "no te entendí"** (empty-cut, no el rojo de cancel).
- **busy/watchdog** (`_PROC_TIMEOUT` 18s): se arma al entrar a procesar; si el turno queda colgado en `thinking` sin llegar a `speaking`, destraba a idle con "no te entendí".

## Otros endpoints del panel (orb_server → socket)
- `say` (Shift+Enter): prompt por TEXTO → `session.generate_reply(user_input=…)` → mismo LLM+TTS, sin grabar voz.
- `stage`: texto del textarea (autosave) → staged en memoria del agente (`vc/attach`), consumido en el turno.

## Orbe sincronizado (U5)
En room el cliente browser sincroniza el orbe con la **voz real**: Web Audio `AnalyserNode`
sobre el track TTS remoto → nivel RMS en vivo. En console era imposible (audio en otro
proceso). El estado (idle/think/speak/…) sigue llegando por SSE desde `orb_server`.

## Notas
- Los plugins (deepgram/silero/noise-cancellation/turn-detector) se importan a NIVEL MÓDULO (se registran en el main thread; importarlos tarde crashea).
- La key se carga de `.env.local` con `python-dotenv` al importar el módulo.
- Sin `DEEPGRAM_API_KEY` → cae solo a whisper/edge (no es config, lo decide la presencia de la key).
