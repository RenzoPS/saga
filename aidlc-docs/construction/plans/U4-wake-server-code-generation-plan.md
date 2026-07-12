# U4 — Wake "hey saga" en el SERVER (sobre el track) · Code Generation Plan (Ciclo 4)

> **CAMBIO DE DISEÑO (decisión del usuario, 2026-06-23):** el wake corre en el SERVER (worker), sobre el
> track de mic del browser — NO en el cliente con onnxruntime-web (U4 original). Razón: evita el port más caro
> (reescribir el pipeline de features del modelo en JS) reusando el wake Python (`livekit.wakeword`) que ya
> existe. Trade-off aceptado: el browser publica el mic CONTINUO (always-listening) cuando el wake está ON;
> el default sigue OFF (mic muteado + Win+Z).

## Factibilidad (verificada, no asumida)
- `WakeWordModel.predict(audio_chunk: np.ndarray) -> dict[str,float]` → el modelo acepta frames crudos.
- `rtc.AudioStream.from_track(track, sample_rate=16000, num_channels=1)` → itera frames del track (`AudioFrame.data`).
- `ctx.room` + `Room.on("track_subscribed")` → el worker agarra el track del mic del browser (source=MICROPHONE).
- El `hey_saga.onnx` (Ciclo 2, FPPH=0) se reusa SIN cambios.

## Stages condicionales (Per-Unit Loop)
- Functional/NFR/Infra Design — SKIP (reusa el modelo + el flujo Win+Z; sin modelos/infra nueva).
- Code Generation — EXECUTE.

## Arquitectura
1. **Worker** (`lk/wakeword.py` + `lk/agent.py`): al suscribirse el track del mic del browser, abrir un
   `rtc.AudioStream` (16kHz mono) EN PARALELO al STT de la AgentSession (dos consumidores del track). Loop:
   frame → numpy → `WakeWordModel.predict` → si el score de "hey_saga" > threshold (con debounce) → `_press()`
   (mismo flujo que Win+Z: abre el turno). El STT sigue gateado por `set_audio_enabled` (solo procesa tras el wake).
2. **Browser** (`orb/orb.html`): con wake ON, el mic se publica DESMUTEADO siempre (el worker necesita el audio
   para oír "hey saga"). Con wake OFF (default), el gate actual (muteado, desmuta en `rec`) se mantiene.
3. **Flag** (`orb/orb_server.py`): `/token` incluye `wake: <bool>` (lee `SAGA_WAKE_ENABLED`). El browser lo usa
   para decidir el muting.

## Detalles a resolver en implementación
- **Chunking**: `WakeWordModel.predict` espera un tamaño de chunk fijo (estilo openWakeWord, ~1280 samples
  @16kHz). Usar `AudioStream(frame_size_ms=...)` o acumular samples hasta el tamaño esperado. Verificar el
  tamaño que espera el modelo (probar con un chunk y ver si predict no rompe).
- **Threshold/debounce**: reusar `SAGA_WAKE_THRESHOLD` + debounce (anti doble-disparo), como el wake actual.
- **Beep**: reusar `vc/sound` (feedback al detectar), como hoy.
- **Dos consumidores del track**: verificar que el AudioStream del wake + el input de la AgentSession coexisten
  (subscripción independiente). Si no, plan B: un `FrameProcessor` en el input de la AgentSession.

## Archivos afectados
| Archivo | Acción | Detalle |
|---|---|---|
| `lk/wakeword.py` | MOD | nuevo modo: wake sobre un `rtc.AudioStream` (track) en vez de WakeWordListener (mic local) |
| `lk/agent.py` | MOD | en room: suscribir el track del mic + arrancar el wake-on-track → `_press` |
| `orb/orb.html` | MOD | con wake ON, publicar el mic desmuteado siempre (no gatear por `rec`) |
| `orb/orb_server.py` | MOD | `/token` incluye `wake` flag (de `SAGA_WAKE_ENABLED`) |

## Riesgos / mitigación
- **Dos consumidores del track** → verificar coexistencia; plan B FrameProcessor.
- **Chunking del modelo** → verificar el tamaño esperado por predict; acumular si hace falta.
- **Falsos positivos** → el modelo (Ciclo 2) tiene FPPH=0 con threshold 0.5; reusar el threshold tuneado.
- **NO romper Win+Z ni el default OFF** → el wake es opt-in (`SAGA_WAKE_ENABLED=1`); con OFF, todo igual que hoy.
- **Verificación**: py_compile + el usuario prueba EN VIVO (decir "hey saga" → graba). El audio no se runtime-testea desde acá.

---

# PART 1 — PLANNING (este documento)
- [x] Step 1-5: factibilidad verificada, diseño, archivos, plan
- [x] Step 6-9: log aprobación + esperar + registrar + Part 1 OK (usuario aprobó 2026-06-23)

# PART 2 — GENERATION (tras aprobación)
- [x] **Step 10**: `lk/wakeword.py` — `WakeWordTrackDetector` (AudioStream → predict → on_wake), reusa modelo+threshold+beep
- [x] **Step 11**: `lk/agent.py` — en room (no console): suscribir track del mic + arrancar el wake-on-track → `_press`
- [x] **Step 12**: `orb/orb_server.py` — `/token` agrega `wake` (de SAGA_WAKE_ENABLED)
- [x] **Step 13**: `orb/orb.html` — con wake ON, publicar mic desmuteado siempre (no gatear por estado)
- [x] **Step 14**: Verificación — py_compile OK + predict smoke (chunking 2s→0.002, 80ms→0.0) ✅ · en vivo PENDIENTE
- [x] **Step 15**: Summary (`U4-wake-server/code/generation-summary.md`) + aidlc-state.md

## Criterio de "U4 hecho"
- Con `SAGA_WAKE_ENABLED=1`: decís "hey saga" → el worker lo detecta sobre el track → abre el turno (como Win+Z).
- Con OFF (default): todo igual que hoy (mic muteado + Win+Z), wake no corre.
- No rompe el flujo de voz ni el dispatch. Verificado en vivo por el usuario.
