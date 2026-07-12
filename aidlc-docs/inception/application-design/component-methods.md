# Component Methods (interfaces de alto nivel) — Ciclo 4

> Firmas/responsabilidades de alto nivel. La lógica detallada va en Functional Design (Construction).

## saga-worker (modo room)
- `entry(ctx)` — entrypoint del worker; se une al room, arma AgentSession (igual que hoy pero el input
  viene del room en vez de console).
- `on_room_audio(track)` — recibe el track de audio del cliente; alimenta STT + wake.
- `_press()` — Win+Z (igual que hoy): idle→rec→busy. Adaptado al input del room.
- wake: reusa `WakeWordDetector` pero su fuente de audio = el track del room (no portaudio local).
- TTS out: publica el audio de respuesta como track al room (en vez de reproducir local).

## saga-client (browser, extiende orb.html)
- `connectRoom(token)` — se une al room con el JWT.
- `publishMic()` — captura el mic (getUserMedia) y publica el track.
- `subscribeTTS(track)` — recibe el track de voz del worker, lo reproduce.
- `animateOrbFromAudio(analyser)` — anima el orbe con el nivel REAL del track TTS (Web Audio AnalyserNode)
  → reemplaza la animación sintética actual. **Esto da el sync real.**
- `onState(state)` — sigue mostrando los estados (idle/rec/think/speak) por SSE como hoy.

## orb_server (+token)
- `GET /token` — genera y devuelve el JWT del cliente (firmado con API_SECRET).
- (resto igual: sirve orb.html, `/state`, `/events` SSE).

## saga-ctl
- `start()` — levanta server (Docker) → daemon → worker (start) → orb_server → abre browser. Readiness.
- `stop()` — drena y baja todo (incluido Docker).
- `status()` — estado por pieza.
