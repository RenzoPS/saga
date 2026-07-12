# Components — Ciclo 4 (modo room)

> Diseño de alto nivel. El cerebro IA (STT/LLM/TTS/VAD/wake model) se conserva; cambia el transporte.

## 1. livekit-server (infra, NUEVO)
- **Qué es**: el servidor de la sala WebRTC. Corre en Docker, local.
- **Responsabilidad**: hostear el room; enrutar tracks de audio entre cliente y worker; despachar jobs al worker.
- **Estado**: nuevo proceso/servicio. Imagen oficial `livekit/livekit-server`. Puertos locales.
- **Interfaz**: WebSocket (signaling) + WebRTC (media). Config por archivo + keys.

## 2. saga-worker (ex `lk/agent.py console` → modo `start`)
- **Qué es**: el agente/cerebro. Se registra en el server, acepta el job, se une al room como participante.
- **Responsabilidad**: recibir el track de audio del cliente → **wake "hey saga" sobre el track** (con wake ON)
  + STT (Deepgram) → VAD/turn detector → LLM (Claude) → TTS (Deepgram) → publicar el track de respuesta al
  room. Mantiene el flujo de fases (idle/rec/busy).
- **Conserva**: ClaudeCodeLLM, Deepgram STT/TTS, Silero VAD, system prompt, socket de control (Win+Z), el
  modelo `hey_saga.onnx` (Ciclo 2).
- **Cambia**: entrypoint `console` → `start`; el audio viene del room (track), no del TCP de console.
  **WAKE (decisión revisada): corre ACÁ, sobre el track** (`rtc.AudioStream` → `WakeWordModel.predict`),
  reusando el wake Python — NO en el cliente con onnxruntime-web (ver component-dependency.md).
- **Interfaz**: LiveKit room (in: track audio cliente; out: track audio TTS) + `LK_CTL_SOCK` (Win+Z).

## 3. saga-client (extiende el ORBE actual)
- **Qué es**: el browser del orbe (orb.html) + LiveKit JS SDK. Es el frontend cliente y, según la visión, EL
  producto (DesktopLayer). **El wake YA NO corre acá** (decisión revisada: pasó al worker, sobre el track).
- **Responsabilidad**: pedir permiso de mic; publicar el track de mic (MUTEADO por default, desmuta en Win+Z;
  **con wake ON lo publica CONTINUO** para que el worker oiga "hey saga"); suscribirse al track TTS y
  reproducirlo; animar el orbe **sincronizado con la voz** (Web Audio AnalyserNode); mostrar estados.
- **Conserva**: orb.html (visual), orb_server (sirve la página + estado + token).
- **Cambia/agrega**: capa de audio LiveKit (publish mic + subscribe TTS), sync real del orbe. SIN wake en JS.
- **Interfaz**: LiveKit room (publish mic / subscribe TTS) + HTTP (`/token` con flag wake, estado).

## 4. token-service (mínimo, NUEVO)
- **Qué es**: endpoint chico que genera el JWT del cliente browser (firmado con API_SECRET local).
- **Responsabilidad**: dar al browser un token válido para unirse al room. El worker usa las keys directo.
- **Ubicación**: en orb_server (un endpoint `/token`) o un helper de saga-ctl. Local.
- **Interfaz**: HTTP GET `/token` → JWT.

## Resumen de cambios por componente
| Componente | Estado | Conserva | Cambia |
|-----------|--------|----------|--------|
| livekit-server | NUEVO | — | Docker local |
| saga-worker | modifica | todo el cerebro IA + Win+Z | entrypoint + fuente de audio |
| saga-client (orbe) | extiende | orb.html + orb_server | + audio LiveKit (mic/TTS) + sync real |
| token-service | NUEVO | — | endpoint JWT local |
