# U7 — LiveKit/room como ÚNICO estándar: eliminar console + flujo clásico · Code Generation Plan (Ciclo 4, cleanup)

## Decisión de diseño (INCEPTION-level, usuario 2026-06-23)
**LiveKit modo ROOM es EL estándar único. Prod. No negociable.** Se ELIMINAN dos caminos legacy:
1. **Transporte console** (`SAGA_TRANSPORT=console` → `lk/agent.py console`): tiene el bug del buffer
   irreparable (Ciclo 3, audio acumulado en idle); fallback dev sin uso; obliga a ramear `_CONSOLE_MODE`.
2. **Flujo clásico** (`VOICE_LIVEKIT=0`: la máquina de turnos standalone `vc/app.py` + whisper_daemon +
   captura portaudio + edge/whisper propios): runtime paralelo entero, pre-LiveKit. Es la "basura" a limpiar.

**Lo único configurable que QUEDA** (decisión del usuario):
- **Wake on/off** (`SAGA_WAKE_ENABLED`).
- **Deepgram o fallback**: con `DEEPGRAM_API_KEY` → Deepgram STT/TTS; sin key → whisper local + edge-tts.
  OJO: ese fallback vive DENTRO del agente LiveKit (`lk/whisper_stt.py`, `lk/edge_tts_plugin.py`) — **NO es**
  el flujo clásico. SE CONSERVA intacto (es el toggle pedido).

**Fuera de scope (NO se toca, decisión explícita):** Vosk / `wake_daemon.py` "queda a ver qué se hace".
Se desconecta del arranque (ya no lo lanza saga-ctl) pero el archivo NO se borra. Queda dormido (depende del
flujo clásico que se va → si se revive, necesita rework). Anotado, no es deuda de este scope.

## Superficie verificada (grep de dependencias, NO de memoria)
- `lk/` reusa de `vc/`: config, sound, runtime(log/_cancel), claudecli, session(is_reset/is_visual),
  desktop, orb, attach → TODOS se conservan.
- `vc/app.py:main()` ES el emisor de Win+Z en room (`_livekit_toggle` → `press` al socket). NO se borra:
  se ADELGAZA a solo eso (+ `--doctor`). Entrypoint `saga = vc.app:main` (Hyprland) intacto.
- `vc/audio.py`, `vc/stt.py`, `vc/tts.py`, `whisper_daemon.py`: importados SOLO por el clásico → BORRABLES.
- `vc/runtime.py`: hub compartido (el path de claude del room usa set_current_proc/kill_current_proc/_cancel).
  Algunos helpers de PID-file quedan sin uso, pero trimearlo es riesgo > beneficio → NO se toca este pase.
- `vc/doctor.py`: NO referencia los flags removidos → no se rompe (sigue como `saga --doctor`).

## Stages condicionales (Per-Unit Loop)
- Functional/NFR/Infra Design — SKIP (refactor de borrado; sin modelos/infra nueva; la decisión de
  transporte queda registrada en este plan + Application Design + aidlc-state).
- Code Generation — EXECUTE.

## Superficie de borrado (verificada en código, no de memoria)

### Código
| Archivo | Acción |
|---|---|
| `vc/config.py` | QUITAR la constante `SAGA_TRANSPORT` (líneas ~206-208) + comentarios asociados (~162, ~207). Room pasa a ser implícito (no hay otro transporte LiveKit). |
| `vcctl.py` | QUITAR `_start_livekit()` entero (~275-331, el path console). `start()` (~458-459): `if LIVEKIT_ENABLED: return _start_room()` (sin branch `SAGA_TRANSPORT`). `status()` (~506-540): sacar `SAGA_TRANSPORT` (transporte = `LIVEKIT/room` si LIVEKIT_ENABLED, si no `clásico`); `if LIVEKIT_ENABLED and SAGA_TRANSPORT=="room"` → `if LIVEKIT_ENABLED`. Limpiar refs a console en comentarios/mensajes (~76, ~363, ~447). |
| `lk/agent.py` | QUITAR `_CONSOLE_MODE` (~71). QUITAR import `noise_cancellation` (~43) + el bloque BVC `_nc` (~281-296) — BVC solo servía en console y NO funciona self-hosted (requiere Cloud) → muerto; `session.start` queda sin `room_options`/noise_cancellation. QUITAR la rama console del wake (~416): el wake queda solo sobre el track (room). Reescribir docstring (~19-28) sin modo console. Limpiar log de transporte (~301-302). Import: `WakeWordDetector` → solo `WakeWordTrackDetector`. |
| `lk/wakeword.py` | QUITAR la clase `WakeWordDetector` (mic local portaudio) — dead con console fuera. CONSERVAR `WakeWordTrackDetector`. Actualizar docstring del módulo (sin portaudio/console). |

### Docs
| Archivo | Acción |
|---|---|
| `.claude/CLAUDE.md` | Sacar console del default/fallbacks; actualizar gotchas (el de "BVC solo console" se va con BVC; el de "console no sincroniza el orbe" se va). Conservar el fallback clásico `VOICE_LIVEKIT=0`. |
| `README.md` | Idem: room único transporte LiveKit; fallback = clásico. |
| `lk/README.md` | Sacar el subcomando `console` y sus menciones; BVC; "wake en el cliente". |

## Notas / riesgos
- **`lk/agent.py console` deja de estar soportado.** La CLI de livekit igual acepta el subcomando
  (es de la lib), pero nuestro código ya no ramea: correrlo a mano ejecutaría la lógica room sin server
  → falla limpio. Documentado, no es un caso de uso.
- **BVC se elimina del todo** (no solo se gatea): solo aplicaba en console y ni ahí self-hosted. Room se
  apoya en el VAD Silero (threshold 0.7), ya presente. Sin pérdida real.
- **El clásico (`VOICE_LIVEKIT=0`) NO se toca**: `vc/app.py`, `whisper_daemon`, `wake_daemon`, `edge_tts`
  quedan. `start()`/`status()` mantienen su rama `else` (clásico).
- **Reversible**: git baseline. El borrado no toca datos ni el modelo de wake.

## Verificación
- `py_compile` de todos los .py tocados + import smoke (agent, wakeword, orb_server, vcctl).
- `grep` de refs colgadas = 0: `_CONSOLE_MODE`, `SAGA_TRANSPORT`, `_start_livekit`, `WakeWordDetector`,
  `noise_cancellation`, `"console"` (en código, no docs).
- El flujo clásico (`VOICE_LIVEKIT=0`) sigue compilando y su path de arranque queda intacto.
- En vivo (usuario): `saga-ctl restart` (room) abre 1 pestaña, despacha, voz andando. (No runtime-testeable desde acá.)

---

# PART 1 — PLANNING (este documento)
- [ ] Step 1-4: decisión registrada, superficie mapeada, plan, aprobación del usuario

# PART 2 — GENERATION (HECHO — 2026-06-23, commit 53d9960)
- [x] **Step 5**: `lk/agent.py` — quitado `_CONSOLE_MODE`, BVC, rama console del wake; docstring; log; imports.
- [x] **Step 6**: `lk/wakeword.py` — quitada `WakeWordDetector`; docstring.
- [x] **Step 7**: `vc/app.py` — adelgazado a `main()` + `_livekit_press` (+`--doctor`). Máquina clásica fuera.
- [x] **Step 8**: BORRADOS `vc/audio.py`, `vc/stt.py`, `vc/tts.py`, `whisper_daemon.py` (git rm).
- [x] **Step 9**: `vcctl.py` — `_start_livekit()` fuera; `start()` → `_start_room()`; `status()` room-only;
      `DAEMONS` sin whisper_daemon; mensajes limpios.
- [x] **Step 10**: `vc/config.py` — fuera `LIVEKIT_ENABLED`/`SAGA_TRANSPORT`/`WAKE_ENABLED` + huérfanas
      (CHANNELS, MIN_DURATION_S, AUTOSTOP_ON_MANUAL, AUDIO_FILE, ABORT_FILE, WHISPER_DAEMON, WHISPER_IDLE_S).
      Conservadas WHISPER_*/EDGE_* (fallback agente), SAMPLE_RATE (wake_daemon), WHISPER_SOCK (doctor).
- [x] **Step 11**: docs (`.claude/CLAUDE.md`, `README.md`, `lk/README.md`) → room único.
- [x] **Step 12**: Verificación — py_compile + import smoke + grep refs=0 (código) + `saga-ctl status`
      room-only + `saga --doctor` OK. Commit 53d9960 + push.

## Criterio "U7 hecho"
- Cero refs en código a: console/`_CONSOLE_MODE`/`SAGA_TRANSPORT`/`LIVEKIT_ENABLED`/`_start_livekit`/
  `WakeWordDetector`/`noise_cancellation`/`vc.audio`/`vc.stt`/`vc.tts`/whisper_daemon.
- `saga-ctl start` arranca room directo. Win+Z (entrypoint `saga`) sigue mandando `press`.
- Toggles vivos: wake on/off + Deepgram-o-fallback. Vosk dormido (fuera de scope).
- py_compile + import smoke OK. En vivo: usuario (1 pestaña, voz andando, Win+Z).
