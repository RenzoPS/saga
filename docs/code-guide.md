# Guía del código (archivo por archivo)

Qué hace cada módulo y cómo encaja. Para el detalle a nivel función, los **docstrings del código
son densos y confiables** — leelos en el archivo.

## Raíz (entrypoints y daemons)

- **`saga.py`** — entrypoint fino del flujo clásico/Win+Z. Solo delega en `vc.app.main`. Es lo que
  llama el wrapper de Hyprland.
- **`vcctl.py`** (`saga-ctl`) — control del ciclo de vida: `start/stop/status/restart`. Mata por
  **ruta exacta del script** leyendo `/proc` (nunca `pkill -f`, que se auto-mataría y pegaría en el
  `claude` CLI). Decide el modo (LiveKit vs clásico) y espera readiness de sockets/puerto.
- **`claude_daemon.py`** — el cerebro caliente: mantiene UN proceso `claude` (stream-json)
  persistente entre turnos. Gestiona sesión (`--session-id` vs `--resume`), reintento ante sesión
  muerta, timeout por turno (180s), reset, anti doble-arranque, auto-apagado a 1h idle.
- **`whisper_daemon.py`** — daemon STT del flujo clásico: modelo faster-whisper caliente en RAM,
  atiende por socket. Auto-apagado a 30 min idle.
- **`wake_daemon.py`** — wake word con Vosk (local, offline). Escucha "claude" con grammar
  restringida + gate de confianza + cooldown. **OFF por default** (`VOICE_WAKE_ENABLED=1`).

## `lk/` — modo LiveKit (default)

- **`lk/agent.py`** — entrypoint del modo default. Arma el `AgentSession` (STT+VAD+LLM+TTS),
  implementa las 3 fases de Win+Z, el socket de control (`press`/`stage`/`say`), y levanta el
  orbe + precalienta Claude. Los plugins de LiveKit se importan a **nivel módulo** (deben
  registrarse en el main thread).
- **`lk/claude_llm.py`** — LLM custom de LiveKit = **el turn handler real del default**. Reenvía el
  último turno del usuario a `claude_daemon`, engancha comandos de voz (reset, visión), consume
  adjuntos staged, y puentea el generador bloqueante de Claude a deltas asyncio (con cancelación en barge-in).
- **`lk/whisper_stt.py`** — adaptador STT faster-whisper para LiveKit (fallback sin Deepgram).
- **`lk/edge_tts_plugin.py`** — plugin TTS edge-tts para LiveKit (fallback sin Deepgram).

## `vc/` — soporte (reusado por ambos modos)

- **`vc/config.py`** — **fuente única** de paths, flags, voces, system prompt, regex (reset/visual),
  y los args base de `claude` (`build_claude_base_args`, compartidos por daemon y one-shot). Sin lógica.
- **`vc/claudecli.py`** — cliente de Claude con dos caminos: daemon (rápido) + fallback one-shot
  (`claude -p`). Maneja imagen (multimodal por stdin), reintento de sesión, y respeta el flag global
  de cancelación.
- **`vc/session.py`** — sesión uuid persistida (escritura atómica) + detección de keywords:
  `is_reset_command`, `is_visual_command`, `is_goodbye` (esta última quedó **sin uso** — código muerto).
- **`vc/attach.py`** — adjuntos del panel, **consume-once**: texto en memoria del proceso agente,
  imagen como path en `/tmp`. `take_staged()` consume en el turno.
- **`vc/desktop.py`** — integración Hyprland: `grim` (screenshot), monitor kitty con tail del log.
- **`vc/runtime.py`** — estado runtime compartido (evita ciclos de import): log rotativo (512KB),
  evento de cancelación, kill de proceso/streamer por grupo, **PID-files anti-recycle** (validan
  `starttime` de `/proc` para que un PID reciclado no se haga pasar por el dueño).
- **`vc/guard.py`** — hook **PreToolUse** de Claude: denylist de bash catastrófico (rm -rf, dd,
  mkfs, fork bomb, git reset --hard, sobrescribir dotfiles…). Fail-open. Función pura `denied()` testeable.
- **`vc/stt.py`** — transcripción del flujo clásico: cliente del daemon Whisper + fallback inline.
- **`vc/tts.py`** — TTS del flujo clásico (módulo grande): limpieza de markdown (`clean_for_tts`),
  microchunking semántico con lookahead (`stream_to_sentences`, `_next_chunk_cut`), y reproducción
  edge-tts → mpg123 (`TTSStreamer`).
- **`vc/audio.py`** — captura de micrófono (sounddevice) + auto-stop por **VAD de voz Silero**
  (detecta habla real, no energía).
- **`vc/sound.py`** — beep de notificación (genera WAV de dos tonos, lo reproduce con `paplay`).
- **`vc/orb.py`** — cliente del orbe: levanta el server si hace falta y manda el **estado** por HTTP
  no bloqueante (cola + keep-alive). No manda nivel de audio (el orbe anima stylized).
- **`vc/doctor.py`** — health check (`saga.py --doctor`): verifica binarios, deps, daemons, config.
  Read-only.
- **`vc/app.py`** — orquestación del flujo clásico (`_do_turn`, locks auto-sanables, abort/zombie) y
  el dispatch de Win+Z: en modo LiveKit solo manda `press` al socket; en clásico corre el turno.

## `orb/` — orbe visual

- **`orb/orb_server.py`** — server persistente (HTTP + SSE), solo stdlib. Sirve la página, emite
  estado por SSE, y hace de **puente HTTP→socket** para el panel (el browser no puede abrir un socket
  Unix). Watchdog que vuelve a idle si saga muere.
- **`orb/orb.html`** — render Three.js del orbe (estados acoplados por bloom). Cuidado: colores de
  fondo en **sRGB** (`THREE.SRGBColorSpace`), sin eso el bloom revienta a blanco.
- **`orb/vendor/`** — Three.js vendorizado (terceros): módulo + postprocessing (UnrealBloom) + shaders.

## `tests/` y `tools/`

- **`tests/test_pure.py`** — unittest de funciones puras: TTS (clean/chunk/flush), keywords de
  sesión, guard denylist, attach consume-once. Es la verificación automatizada del repo.
- **`tools/say.py`** — utilidad TTS suelta (auxiliar, no test).
