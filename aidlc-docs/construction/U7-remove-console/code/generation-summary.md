# U7 — LiveKit/room estándar único · Generation Summary (Ciclo 4, cleanup)

> Code Generation ejecutado 2026-06-23. Commit `53d9960`. Plan: `plans/U7-remove-console-code-generation-plan.md`.
> Decisión del usuario: room es el estándar único, no negociable. Se eliminan console + flujo clásico.

## Qué se hizo
Room (LiveKit) queda como ÚNICO camino. Eliminados dos legacy:
1. **Transporte console** (`SAGA_TRANSPORT=console`) — bug del buffer irreparable + glue `_CONSOLE_MODE`.
2. **Flujo clásico** (`VOICE_LIVEKIT=0`) — máquina de turnos standalone (`vc/app.py`) + STT/TTS propios.

**Único configurable que queda:** wake on/off (`SAGA_WAKE_ENABLED`) + Deepgram-o-fallback (con key →
Deepgram; sin key → faster-whisper + edge-tts DENTRO del agente, `lk/whisper_stt.py`/`lk/edge_tts_plugin.py`).

## Cambios
| Archivo | Acción |
|---|---|
| `vc/audio.py`, `vc/stt.py`, `vc/tts.py`, `whisper_daemon.py` | **BORRADOS** (clásico-only, 0 importadores compartidos) |
| `vc/app.py` | Adelgazado de 236 → 44 líneas: `main()` + `_livekit_press` (emisor Win+Z) + `--doctor`. Máquina de turnos clásica fuera. Entrypoint `saga = vc.app:main` (Hyprland) intacto. |
| `lk/agent.py` | Fuera `_CONSOLE_MODE`, BVC (`noise_cancellation`), rama console del wake; queda wake-on-track (U4). `session.start` sin `room_options`. Imports limpios (sin `room_io`, `WakeWordDetector`). |
| `lk/wakeword.py` | Fuera `WakeWordDetector` (mic local portaudio); queda `WakeWordTrackDetector`. |
| `vcctl.py` | Fuera `_start_livekit()`; `start()` → `_start_room()` directo; `status()` room-only; `DAEMONS` sin whisper_daemon; mensajes sin console/clásico. |
| `vc/config.py` | Fuera `LIVEKIT_ENABLED`, `SAGA_TRANSPORT`, `WAKE_ENABLED` (VOICE_WAKE_ENABLED) + huérfanas. Conservadas WHISPER_*/EDGE_* (fallback), SAMPLE_RATE (wake_daemon), WHISPER_SOCK (doctor), PID/LOCK_FILE (runtime). |
| docs | `.claude/CLAUDE.md`, `README.md`, `lk/README.md` → room único. |

## Decisiones conservadoras (no romper)
- **`vc/runtime.py` NO se tocó**: hub compartido (el path de claude del room usa set_current_proc/
  kill_current_proc/_cancel). Algunos helpers de PID-file quedan sin uso; trimearlos era riesgo > beneficio.
- **`wake_daemon.py` (Vosk) NO se borró**: dormido, fuera de scope (decisión explícita del usuario). Ya no lo
  lanza saga-ctl; si se revive necesita rework (dependía del flujo clásico). Anotado.
- **`vc/doctor.py` intacto** (`saga --doctor`): no referencia flags removidos; corre.

## Verificación
- `py_compile` de todo OK. Import smoke OK (vcctl, saga, vc.*, lk.*, orb_server).
- `grep` de refs colgadas en código = 0 (`_CONSOLE_MODE`/`SAGA_TRANSPORT`/`LIVEKIT_ENABLED`/`_start_livekit`/
  `WakeWordDetector`/`vc.audio`/`vc.stt`/`vc.tts`/`whisper_daemon`).
- `saga-ctl status` → "LiveKit / room", server+worker UP, wake_daemon "dormido". `saga --doctor` corre.
- Net: ~1300 líneas menos.
- **Pendiente (usuario, en vivo)**: `saga-ctl restart` → 1 pestaña, voz andando, Win+Z. (No runtime-testeable acá.)
