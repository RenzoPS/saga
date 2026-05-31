# voice-claude

Asistente de voz para Linux/Hyprland: **voz → Claude Code → voz**, con un orbe 3D
que reacciona al estado y al audio. Toggle por hotkey (Win+Z), cancelable.

## Flujo

```
Win+Z → grabar mic → Whisper (STT) → claude CLI (stream) → edge-tts (TTS) → parlante
                          ↑ daemon caliente            orbe SSE sigue cada fase ↑
```

Pipeline: grabación (sounddevice) → transcripción (faster-whisper) → respuesta
(Claude CLI en `stream-json`) → síntesis (edge-tts → mpg123 → pacat con metering
RMS que alimenta el orbe).

## Requisitos

- Python 3 + el venv del proyecto (`.venv/`)
- Binarios del sistema: `claude` (CLI), `mpg123`, `pacat` (PipeWire/PulseAudio),
  `grim` (screenshot), `hyprctl`/`kitty`/`xdg-open` (Hyprland)
- Hotkey: bind de Hyprland a `~/.local/bin/voice-claude`

## Setup

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Correr

```bash
.venv/bin/python voice_claude.py     # o el wrapper ~/.local/bin/voice-claude (Win+Z)
```

- 1er Win+Z: empieza a grabar (+ precalienta el daemon Whisper en paralelo).
- 2do Win+Z: corta y procesa.
- Win+Z durante respuesta: cancela.
- Decir "nueva sesión" / "empezamos de cero": resetea el contexto conversacional.

## Tests

```bash
.venv/bin/python -m unittest tests.test_pure
```

## Variables de entorno

| Var | Default | Qué hace |
|-----|---------|----------|
| `VOICE_CLAUDE_SAFE` | (off) | `=1` desactiva `--dangerously-skip-permissions` |
| `VOICE_WHISPER_SIZE` | `small` | modelo Whisper (`tiny`/`base`/`small`/...) |
| `VOICE_WHISPER_BEAM` | `5` | beam search (bajar = más rápido, más alucinación) |
| `VOICE_CLAUDE_MEM_DIR` | autodetect | override del plugin-dir de claude-mem |
| `ORB_PORT` | `8777` | puerto del server del orbe |

## Arquitectura

Entry point fino `voice_claude.py` → paquete `vc/`:

| Módulo | Responsabilidad |
|--------|-----------------|
| `config.py` | constantes, paths, flags, regexes (autodetecta versión de claude-mem) |
| `runtime.py` | log, evento de cancelación, control de procesos, signals, PID-files |
| `audio.py` | grabación del mic |
| `stt.py` | cliente del daemon Whisper + fallback inline |
| `session.py` | sesión (uuid) + keywords (reset/visual) |
| `claudecli.py` | spawn de `claude` en stream-json + system prompt |
| `tts.py` | limpieza, microchunking, pipeline edge-tts + metering |
| `orb.py` | cliente HTTP del orbe (estado/nivel) |
| `desktop.py` | Hyprland (notify/monitor) + screenshot (grim) |
| `app.py` | orquestación: stop/abort/start + main |

Procesos persistentes (sobreviven entre invocaciones):
- `whisper_daemon.py` — modelo Whisper caliente en RAM (socket Unix).
- `orb/orb_server.py` — server SSE + estático que sirve `orb/orb.html` (Three.js vendoreado en `orb/vendor/`).
