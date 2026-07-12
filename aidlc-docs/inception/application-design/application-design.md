# Application Design (consolidado) — Ciclo 4: migración a modo room

**Fecha**: 2026-06-23 · **Tipo**: Migration/Refactor del transporte de audio · **Solo documentación**.

## Resumen
Migrar el transporte de audio de **modo console** (atajo de dev, mic siempre conectado → buffer/backlog,
Ciclo 3) a **modo room** (la arquitectura estándar de LiveKit: worker + room + frontend client + WebRTC).
El cerebro IA (Deepgram STT/TTS, Claude, Silero VAD, BVC, modelo wake) se conserva intacto. Fundamento:
worker+room+client es el patrón de producción documentado de LiveKit (docs.livekit.io/agents/overview,
/build/anatomy) — mantenible, escalable, multi-cliente (web hoy, desktop/móvil mañana).

## Componentes (ver components.md)
1. **livekit-server** (Docker local, NUEVO) — la sala WebRTC.
2. **saga-worker** (ex console → modo `start`) — el cerebro; recibe track de audio, corre STT/wake/VAD/LLM/TTS,
   publica la respuesta. Conserva ClaudeCodeLLM, Deepgram, Silero, BVC, Win+Z.
3. **saga-client** (extiende el orbe) — browser con LiveKit JS SDK: publica mic, recibe TTS, **anima el orbe
   sincronizado con la voz real**.
4. **token-service** (endpoint local en orb_server) — JWT para el cliente.

## Flujo (ver component-dependency.md)
browser publica mic → server → worker (wake/STT/LLM/TTS) → publica TTS → server → browser reproduce + anima.
**Resuelve el buffer**: en room los frames se descartan cuando el turno no está activo (nativo, verificado
en `room_io/_input.py:154-156`).

## Orquestación (ver services.md)
saga-ctl levanta: server (Docker) → daemon → worker (start) → orb_server (+token) → browser cliente.
Console queda como fallback dev (env `SAGA_TRANSPORT`, default room).

## Decisiones clave (Application Design)
- Cliente = extender el orbe (no cliente nuevo). **Wake = en el SERVER, sobre el track** (decisión REVISADA
  2026-06-23 — antes era "en el cliente/onnxruntime-web"; se cambió para reusar el wake Python y evitar el
  port a JS; ver component-dependency.md "Por qué el wake en el SERVER"). Trade-off: mic continuo con wake ON
  (opt-in, default OFF). Tokens = endpoint local. Win+Z = se conserva. Console = fallback. Estilo = LiveKit estándar.

## Alineación con la visión de producto (vault: "saga — Estrategia de Producto")
Saga NO es un wrapper de voz — es la **capa de escritorio (DesktopLayer) que convierte cualquier agente IA
en un Jarvis**, cross-platform (Linux → Windows → macOS), con LiveKit como cimiento fijo/gratis. La migración
a room REFUERZA esa visión:
- **Cliente desacoplado del cerebro** → habilita app de escritorio (Electron/Tauri) + multi-dispositivo +
  multi-backend futuro (el `Brain` swappable). Room es el cimiento de todo eso.
- **Wake en el cliente** → coherente con "el cliente es el producto": orbe + hotkey + wake + screenshot
  viven en la capa de cliente, portable.
- **Consideración (trade-off real)**: el vault marca que "el instalable por un extraño" es el paso #1 para
  producto. Room agrega Docker + livekit-server → MÁS fricción de instalación que console. A resolver en el
  empaquetado (embeber el server / install.sh / AUR). No bloquea el ciclo, pero se registra.
- **Oportunidad (fuera de scope)**: la deuda D1 (lógica de turno duplicada clásico/LiveKit, ver
  tech-debt-plan.md) podría limpiarse al rearmar el transporte. NO en el Ciclo 4.

## Riesgos / a resolver en Construction (Functional/Infra Design)
1. **Cliente publicador (browser)** = el grueso del trabajo nuevo (LiveKit JS SDK, getUserMedia, permisos).
2. **Wake sobre el track**: validar que `WakeWordDetector` consuma el track del room en vez de portaudio.
3. **saga-ctl orquestando Docker**: gestión del server, readiness, drain en stop.
4. **Latencia (NFR duro)**: medir WebRTC local; esperado ~ms, pero el NFR exige benchmark en vivo.
5. **Win+Z con audio del room**: re-cablear el flujo de fases al nuevo input.
6. **Seguridad** (a evaluar): el server expone puertos locales; revisar binding (localhost-only).

## Próximas etapas (NO en este ciclo — requieren aprobación)
- Units Generation (opcional): descomponer en server-infra / worker / cliente-mic / orbe-sync.
- Construction: Functional Design + Infrastructure Design + Code Generation + Build&Test (con benchmark).

## Lo que NO entra (Ciclo 5)
Speaker verification "solo mi voz" — diferido, ciclo aparte.
