# Units of Work — Ciclo 4 (migración a modo room)

> Descomposición del trabajo en unidades implementables. Brownfield (monolito modular: paquete `lk/`+`vc/`
> + orbe web + daemons). NO se construye en este ciclo — esto es el mapa para Construction futura.

## U1 — Infra room (livekit-server + tokens)
- **Qué**: levantar `livekit-server` (Docker), config local, generar keys (LIVEKIT_URL/API_KEY/API_SECRET en
  `.env.local`), y el endpoint `/token` (en orb_server) que emite el JWT del cliente.
- **Entregable**: docker-compose/run del server + config + token endpoint.
- **Riesgo**: binding localhost-only (seguridad), puertos.

## U2 — Worker en modo room (ex console)
- **Qué**: migrar `lk/agent.py` de `console` → `start --url ... --api-key ... --api-secret ...`. El input de
  audio viene del track del room (no del TCP console). Adaptar el flujo de fases y Win+Z al nuevo input.
- **Conserva**: ClaudeCodeLLM, Deepgram STT/TTS, Silero VAD, BVC, claude_daemon, `LK_CTL_SOCK`.
- **Entregable**: worker que se registra en el server y atiende el room.
- **Riesgo**: re-cablear Win+Z/fases; que el cerebro IA quede intacto.

## U3 — Cliente de audio (browser publica/recibe)
- **Qué**: agregar LiveKit JS SDK al orbe (orb.html): unirse al room con el token, publicar el track de mic
  **on-demand**, suscribirse al track TTS y reproducirlo.
- **Entregable**: el browser como participante de audio del room.
- **Riesgo**: permisos de mic (getUserMedia), el grueso del trabajo nuevo.

## U4 — Wake en el SERVER, sobre el track (decisión revisada 2026-06-23)
> Antes: "wake en el cliente (onnxruntime-web)". CAMBIADO a server-on-track por decisión del usuario —
> evita portar el pipeline del modelo a JS (frankenstein), reusando el wake Python. Ver component-dependency.md.
- **Qué**: el worker corre el wake "hey saga" sobre el track del mic del browser (`rtc.AudioStream` 16kHz →
  `WakeWordModel.predict`, reusando `lk/wakeword.py` + `hey_saga.onnx`), en PARALELO al STT. Al detectar →
  `_press()` (abre el turno). Win+Z también. El browser publica el mic CONTINUO con wake ON (opt-in).
- **Entregable**: wake server-side sobre el track que dispara el turno. `/token` informa el flag wake.
- **Riesgo**: dos consumidores del track (wake AudioStream + STT) deben coexistir; el chunking que espera
  `predict`. El modelo (Ciclo 2) se reusa sin cambios. SIN port a JS.
- **Depende de**: U3 (el track del mic del browser).

## U5 — Orbe sincronizado con la voz real
- **Qué**: animar el orbe con el nivel REAL del track TTS (Web Audio AnalyserNode), reemplazando la animación
  sintética actual. Resuelve el sync que en console era imposible.
- **Entregable**: orbe que late con la voz de saga.
- **Depende de**: U3 (recibe el track TTS).

## U6 — saga-ctl orquestación
- **Qué**: que saga-ctl levante/monitoree server (Docker) + daemon + worker (start) + orb_server(+token) +
  abrir browser. Readiness por pieza. stop = drena y baja todo. Mantener console como fallback (env).
- **Entregable**: `saga-ctl start/stop/status` para el modo room.
- **Depende de**: U1, U2, U3.

## Resumen
| Unidad | Capa | Trabajo | Reusa |
|--------|------|---------|-------|
| U1 infra | server/infra | nuevo (Docker + token) | — |
| U2 worker | backend | migrar entrypoint | todo el cerebro IA |
| U3 cliente audio | frontend | nuevo (LiveKit JS) | orb.html |
| U4 wake **server** | backend | wake sobre el track (AudioStream→predict) | lk/wakeword.py + hey_saga.onnx |
| U5 orbe sync | frontend | nuevo (Web Audio) | orb.html |
| U6 saga-ctl | orquestación | ampliar | vcctl.py |
