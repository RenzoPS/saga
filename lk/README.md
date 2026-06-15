# lk/ — modo LiveKit (default)

Agente de voz sobre **LiveKit Agents**. LiveKit es dueño del runtime de audio (captura,
streaming, chunks, VAD, fin-de-turno, barge-in, cancelación de ruido BVC). Nosotros
enchufamos STT/cerebro/TTS. Ver el `README.md` de la raíz para el panorama completo.

## Piezas
- `agent.py` — entrypoint. `AgentSession` con STT/LLM/TTS + 3 fases Win+Z + socket de control + orbe.
- `claude_llm.py` — LLM custom: delega en `claude_daemon` (cerebro) y dispara visión (grim) en comandos visuales.
- `whisper_stt.py` — STT de fallback (faster-whisper local) si no hay `DEEPGRAM_API_KEY`.
- `edge_tts_plugin.py` — TTS de fallback (edge-tts) si no hay key.

## Stack por default (si hay DEEPGRAM_API_KEY)
- STT: `deepgram.STT("nova-3", language="es")` — streaming.
- TTS: `deepgram.TTS("aura-2-gloria-es")` — voz española neutra.
- Ruido: `noise_cancellation.BVC()` en `room_input_options` (saca fondo antes del VAD).
- Fin de turno: `turn_detection="vad"`, ~2s de silencio.

## Correr
```bash
vc-ctl start                              # recomendado (lo gestiona vcctl)
.venv/bin/python lk/agent.py console      # directo (audio local, sin servidor)
```

## Win+Z (3 fases, vía socket de control LK_CTL_SOCK)
idle→graba · grabando→corta y manda · procesando→mata. Silencio ~2s también manda.

## Notas
- El plugin de Deepgram/silero/noise-cancellation se importa a NIVEL MÓDULO (se registra
  en el main thread; importarlo tarde crashea).
- La key se carga de `.env.local` con `python-dotenv` al importar el módulo.
- Sin key → cae solo a whisper/edge (no es config, lo decide la presencia de la key).
