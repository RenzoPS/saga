# Component Dependency / Flujo de audio — Ciclo 4 (modo room)

## Topología
```
   ┌──────────────────────── livekit-server (Docker, local) ────────────────────────┐
   │                              la SALA (room)                                      │
   └─────────────▲───────────────────────────────────────────────▲──────────────────┘
                 │ mic track (browser publica)                    │ TTS track (worker publica)
                 │                                                │
        ┌────────┴─────────┐                            ┌─────────┴──────────┐
        │  saga-client     │                            │   saga-worker      │
        │  (browser orbe)  │                            │   (el cerebro)     │
        │  - captura mic   │                            │  - recibe mic track│
        │  - publica track │                            │  - STT (Deepgram)  │
        │  - recibe TTS    │◀───────────────────────────│  - WAKE + VAD      │
        │  - anima orbe    │   TTS track (voz saga)     │  - LLM (Claude)    │
        │    SINCRONIZADO  │                            │  - TTS (Deepgram)  │
        └──────────────────┘                            │  - publica TTS     │
                 ▲                                       └─────────┬──────────┘
                 │ HTTP /token, /state                            │ LK_CTL_SOCK (Win+Z press)
        ┌────────┴─────────┐                            ┌─────────┴──────────┐
        │   orb_server     │                            │  claude_daemon     │
        │  (+endpoint token)│                           │  (cerebro caliente)│
        └──────────────────┘                            └────────────────────┘
```

## Flujo de un turno (wake en el SERVER — decisión revisada 2026-06-23)
**Con wake OFF (default):** el browser publica el mic MUTEADO; desmuta en Win+Z (`rec`). El worker procesa
el track solo cuando está activo. No hay wake.
**Con wake ON (`SAGA_WAKE_ENABLED=1`, always-listening):**
1. El browser publica el mic CONTINUO (desmuteado). El worker recibe el track.
2. El worker corre el **wake "hey saga" sobre el track** (`rtc.AudioStream` 16kHz → `WakeWordModel.predict`),
   EN PARALELO al STT (que sigue gateado: no procesa hasta el wake). Win+Z también abre el turno.
3. Detecta "hey saga" (o Win+Z) → abre el turno (`set_audio_enabled(True)`) → STT (Deepgram) transcribe.
4. VAD/turn detector cierra el turno → LLM (Claude vía daemon) → respuesta.
5. TTS (Deepgram) → worker publica el track TTS → browser lo reproduce + **anima el orbe sincronizado**.
6. Vuelve a idle (el worker sigue corriendo el wake sobre el track).

## Por qué el wake en el SERVER (no en el cliente) — DECISIÓN REVISADA
**Decisión original (Application Design):** wake en el CLIENTE (onnxruntime-web) — por patrón estándar LiveKit,
privacidad (mic no sale hasta el wake) y cross-platform.
**Decisión revisada (usuario, 2026-06-23):** wake en el SERVER, sobre el track del mic del browser.
- **Por qué se cambió**: portar el pipeline de features del modelo a JS (onnxruntime-web) es el trabajo más
  caro/riesgoso del ciclo (frankenstein). El SERVER reusa el wake Python (`livekit.wakeword`, `WakeWordModel.
  predict` acepta frames) sobre el track — sin reescribir nada. `hey_saga.onnx` (Ciclo 2) se reusa igual.
- **Trade-off aceptado**: con wake ON el mic streamea CONTINUO al worker (always-listening estilo Alexa) →
  se pierde la privacidad "el mic no sale hasta el wake" del enfoque cliente. Mitigado: el wake es OPT-IN
  (default OFF = mic muteado + Win+Z); el server es local (audio no sale de la máquina). Cross-platform: el
  wake deja de ser portable al cliente, pero el cerebro sigue server-side de todos modos.
- **Alineado con** `component-methods.md` (que ya preveía "wake reusa WakeWordDetector, fuente = el track del room").

## Por qué esto resuelve el buffer (Ciclo 3)
En room, cuando el turno no está activo, el worker **descarta los frames** del track (mecanismo nativo
`room_io/_input.py:154-156`, `on_detached`). No hay backlog acumulado como en console. Confirmado en código.

## Dependencias (quién necesita a quién)
| Componente | Depende de |
|-----------|------------|
| saga-client (orbe) | livekit-server (room), orb_server (token/estado) |
| saga-worker | livekit-server (room), claude_daemon (LLM), Deepgram (STT/TTS), modelo wake |
| orb_server | — (sirve página + token + estado) |
| token-service | API_SECRET (.env.local) |
| livekit-server | Docker, keys |

## Comunicación
- **Audio**: WebRTC (cliente ↔ server ↔ worker). Baja latencia, local (~ms).
- **Control (Win+Z)**: Unix socket `LK_CTL_SOCK` (Win+Z proc → worker), igual que hoy.
- **Estado/token**: HTTP (browser ↔ orb_server).
- **Cerebro**: Unix socket (worker ↔ claude_daemon), igual que hoy.
