# voice-claude

Asistente de voz para Linux/Hyprland: **voz → Claude Code → voz**, sobre **LiveKit**
(runtime de audio) + **Deepgram** (STT/TTS), con un orbe 3D que reacciona al estado.
Push-to-talk con Win+Z.

## Flujo

```
Win+Z → LiveKit (mic, streaming, VAD, turn, barge-in, BVC noise-cancel)
        → Deepgram Nova-3 (STT streaming)
        → Claude Code (daemon caliente, el cerebro: responde y hace cosas en la compu)
        → Deepgram Aura-2 (TTS, voz es. gloria)
        → parlante
        (el orbe sigue cada fase por un socket de control)
```

**LiveKit es dueño de todo el runtime de audio** (captura, chunks, streaming, detección
de fin de turno, barge-in, cancelación de ruido). Nosotros enchufamos las piezas: STT,
cerebro y TTS. El cerebro es **Claude Code** (no una API plana) → puede ejecutar bash,
leer archivos, usar MCP: hace cosas en la máquina, no solo conversa.

### Latencias típicas (con Deepgram)
STT ~0.3s · Claude TTFT ~2s · TTS ttfb ~0.3s → **~2-3s de "callaste" a "te habla"**.

## Requisitos

- Python 3.12 + venv del proyecto (`.venv/`).
- **`DEEPGRAM_API_KEY`** en `.env.local` (cuenta free de deepgram.com; gitignored).
  Sin la key, cae solo a fallback local (faster-whisper + edge-tts, más lento).
- Binarios: `claude` (CLI), `mpg123`, `grim` (screenshot), `hyprctl`/`kitty`/`xdg-open`.
- Hotkey: bind de Hyprland a `~/.local/bin/voice-claude` (Win+Z).

## Setup

```bash
uv pip install --python .venv/bin/python -e .   # o pip install -e .
echo 'DEEPGRAM_API_KEY=tu_key' > .env.local      # gitignored, NO se commitea
```

## Correr

```bash
vc-ctl start      # levanta el agente LiveKit + Claude + orbe + monitor
vc-ctl status     # ver modo, stack (Deepgram vs fallback) y daemons
vc-ctl stop       # apagar todo
```

### Uso (Win+Z, push-to-talk de 3 fases)
- **idle → Win+Z**: empieza a grabar (orbe "Grabando").
- **grabando → Win+Z**: corta y manda el turno (o esperá ~2s de silencio, manda solo).
- **procesando/hablando → Win+Z**: mata la respuesta en curso (orbe "Cancelado").
- **Visión on-demand**: decí "mirá la pantalla", "fijate esto", "qué ves" → captura con
  grim, se la manda a Claude, y la borra (privacidad).

## Stack

| Pieza | Tecnología | Notas |
|-------|-----------|-------|
| Runtime audio | **LiveKit Agents** (modo `console`, local, sin servidor) | captura/stream/VAD/turn/barge-in |
| Cancelación ruido | **BVC** (Krisp, `livekit-plugins-noise-cancellation`) | saca guitarra/voces de fondo |
| STT | **Deepgram Nova-3** (streaming) | fallback: faster-whisper local |
| Cerebro | **Claude Code** (`claude_daemon`, stream-json) | ejecuta tools/bash/MCP |
| TTS | **Deepgram Aura-2** (voz `aura-2-gloria-es`) | fallback: edge-tts |
| Orbe | server SSE + Three.js, manejado por socket de control | identidad visual |

## Variables de entorno

El stack se decide **solo** (Deepgram si hay key, fallback si no) — NO hay flags para
elegir proveedor. Los únicos toggles:

| Var | Default | Qué hace |
|-----|---------|----------|
| `VOICE_LIVEKIT` | `1` (on) | `=0` vuelve al flujo clásico (Win+Z por-turno, whisper/edge) |
| `VOICE_CLAUDE_SAFE` | (off) | `=1` desactiva `--dangerously-skip-permissions` |
| `VOICE_CLAUDE_MEM` | `0` (off) | `=1` activa claude-mem en voz (+2-7s/turno; respawnear daemon) |
| `ORB_PORT` | `8777` | puerto del server del orbe |

## Arquitectura

Modo LiveKit (default) — paquete `lk/`:

| Módulo | Responsabilidad |
|--------|-----------------|
| `lk/agent.py` | entrypoint: arma `AgentSession`, 3 fases Win+Z, socket de control, orbe |
| `lk/claude_llm.py` | LLM custom de LiveKit que delega en `claude_daemon` (+ visión grim) |
| `lk/whisper_stt.py` | STT de fallback (faster-whisper) si no hay Deepgram |
| `lk/edge_tts_plugin.py` | TTS de fallback (edge-tts) si no hay Deepgram |

Soporte (paquete `vc/`, reusado): `config` (paths/flags/secretos) · `claudecli` +
`claude_daemon.py` (cerebro caliente) · `orb` + `orb/orb_server.py` (orbe) ·
`desktop` (grim/Hyprland) · `runtime` · `session`. El flujo clásico (`vc/app.py`,
`whisper_daemon.py`, wake `Vosk`) queda como fallback (`VOICE_LIVEKIT=0`).

Control: `vcctl.py` (`vc-ctl`) lanza el agente, abre el monitor y espera readiness.
Win+Z (`vc/app.py` → `_livekit_toggle`) le manda `press` al socket del agente.

## Privacidad

En modo Deepgram, el audio del mic viaja a Deepgram en streaming (precio de la
velocidad). La key vive en `.env.local` (gitignored). Las capturas de pantalla se
borran inmediatamente tras mandarlas a Claude. Para todo-local: `VOICE_LIVEKIT=0`.
