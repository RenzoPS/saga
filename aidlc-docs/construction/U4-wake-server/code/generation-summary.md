# U4 — Wake "hey saga" server-side (sobre el track) · Generation Summary (Ciclo 4)

> Code Generation Part 2 ejecutado 2026-06-23. Plan: `plans/U4-wake-server-code-generation-plan.md`.
> Diseño aprobado por el usuario (server-on-track, no cliente onnxruntime-web).

## Qué se hizo

Wake word "hey saga" en modo room corriendo en el **SERVER** (worker), sobre el track del mic del
browser. Al detectar la frase, dispara `_press()` → mismo flujo que Win+Z (abre el turno). Reusa el
modelo `hey_saga.onnx` (Ciclo 2, FPPH=0) y el wake Python (`livekit.wakeword`) SIN portarlo a JS.
Opt-in: `SAGA_WAKE_ENABLED=1`. Default OFF (mic muteado + Win+Z, igual que hoy).

## Archivos (4, como el plan)

| Archivo | Cambio |
|---|---|
| `lk/wakeword.py` | **+`WakeWordTrackDetector`**: consume `rtc.AudioStream.from_track(track, sample_rate=16000, num_channels=1, frame_size_ms=80)`. Ventana deslizante de 2s (deque, 25 frames × 1280 samples) → `WakeWordModel.predict` en executor cada ~240ms (PREDICT_EVERY=3) → debounce → beep → `on_wake`. Reusa modelo/threshold/beep de la clase local. |
| `lk/agent.py` | import `rtc` + `WakeWordTrackDetector`. En room (no console) con wake ON: `ctx.room.on("track_subscribed")` + barrido de tracks ya presentes → al llegar el mic (KIND_AUDIO + SOURCE_MICROPHONE) arranca un único `WakeWordTrackDetector`. Console sigue con `WakeWordDetector` (mic local). Docstring actualizado. |
| `orb/orb_server.py` | `/token` agrega `"wake": <bool>` (de `SAGA_WAKE_ENABLED`, parseo seguro anti `bool("0")`). |
| `orb/orb.html` | lee `wake` del `/token`. Con wake ON: `publishMic` deja el mic DESMUTEADO siempre y el gate `orbstate` no re-mutea. Con OFF: comportamiento actual (muteado, desmuta en `rec`). |

## Decisiones de implementación

- **Cadence de predict**: cada 3 frames (~240ms), no por-frame como el listener nativo (~80ms). El wake
  dura ~1s → no se pierde; baja la carga de CPU (mel+embeddings sobre 2s es lo caro). Tuneable.
- **frame_size_ms=80** → 1280 samples/frame @16kHz: el AudioStream resamplea el track (browser suele
  enviar 48kHz) a 16kHz mono y entrega el tamaño que espera el modelo. Sin resampleo manual.
- **El detector lee el track directo**, independiente de `session.input.set_audio_enabled(False)`: oye
  siempre aunque el STT esté gateado. El STT solo procesa tras el wake (cuando `_press` lo habilita).
- **Un solo detector** aunque lleguen varios `track_subscribed` (guard `_wake_track["d"]`).

## Verificación

- `py_compile` OK (`lk/agent.py lk/wakeword.py orb/orb_server.py`).
- Import smoke OK (los 3 módulos importan).
- `predict` smoke (chunking, sin audio real): chunk 2s silencio → `hey_saga`=0.002 (sin falso positivo);
  chunk 80ms → 0.0 (rama de guarda `< EMBEDDING_WINDOW`). CHUNK_FRAMES=25 → 32000 samples = 2s. ✅
- **PENDIENTE (usuario, en vivo)**: con `SAGA_WAKE_ENABLED=1` + `saga-ctl start`, decir "hey saga" →
  el orbe pasa a "Grabando". El audio no se runtime-testea desde acá (mic/WebRTC).

## Riesgos abiertos (a confirmar en vivo)

1. **Dos consumidores del track** (AudioStream del wake + STT de la AgentSession): la API de LiveKit
   soporta múltiples AudioStream sobre el mismo track; a confirmar que coexisten sin pisarse. Plan B
   (si fallan): un `FrameProcessor` en el input de la sesión en vez de un stream aparte.
2. **Falsos positivos**: threshold default 0.92 (env `SAGA_WAKE_THRESHOLD` lo tunea). El modelo tiene
   FPPH=0 en validación; confirmar en vivo con ruido real.
3. **Privacidad/ancho de banda**: con wake ON el mic va continuo al server (local-only). Mitigado:
   default OFF + opt-in explícito.

## Criterio "U4 hecho"
- [x] Código generado (4 archivos) + verificación estática (py_compile + predict smoke).
- [ ] Validación en vivo del usuario ("hey saga" → graba; OFF = todo igual que hoy). ← ÚNICO pendiente.
