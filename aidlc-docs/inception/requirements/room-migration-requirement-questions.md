# Ciclo 4 — Migración de modo console → modo room (LiveKit) — Requirements

> Estado: **COMPLETO** (decisiones tomadas 2026-06-23 por el AI a pedido del usuario, que delegó
> las respuestas). Solo planificación/documentación — SIN código en este ciclo.

## Intent Analysis
- **User request**: el wake en modo console es inviable por el buffer acumulado (Ciclo 3 lo diagnosticó).
  Migrar al modo **room** de LiveKit (servidor real), donde el control del input de audio sí funciona
  (los frames se descartan cuando el mic está "apagado" — verificado en código, `room_io/_input.py:154-156`).
- **Request type**: Refactoring / Migration (cambia el transporte de audio, NO el cerebro IA).
- **Scope**: Multiple Components (entrypoint del agente, saga-ctl, cliente de audio, orbe). System-wide
  en transporte; el stack de IA queda intacto.
- **Complexity**: Complex (rearquitectura del transporte; pieza nueva = cliente publicador del mic).

## Motivación (por qué room, no solo el buffer)
1. **Fix del buffer** → wake usable (la razón principal).
2. **Orbe sincronizado con la voz real** → el orbe se conecta como participante al room y recibe el track
   TTS → animación sincronizada de verdad (algo que en console documentamos como IMPOSIBLE).
3. **Multi-dispositivo** → hablarle a saga desde el celular/otra compu en la misma red.
4. **Modo producción** de LiveKit (no el atajo de prueba `console`).
5. **Latencia**: el transporte es WebRTC sobre localhost (~ms), despreciable vs Deepgram+Claude (2-3s).
   NFR de velocidad se mantiene (a confirmar con benchmark).

## Lo que se CONSERVA (cerebro IA, intacto)
Deepgram STT (Nova-3) · Deepgram TTS (Aura-2) · ClaudeCodeLLM + claude_daemon · Silero VAD ·
noise_cancellation (BVC) · wake word model (`hey_saga.onnx`) · orbe (orb_server) · vc/ · system prompt.
Son agnósticos al modo (console/room) — no se tocan.

## Decisiones del ciclo (respondidas por el AI; usuario delegó)

### Q1: Servidor LiveKit — self-hosted Docker local vs LiveKit Cloud
**[Answer]: Docker self-hosted LOCAL.** Razones: gratis; el audio NO sale de la máquina (privacidad,
coherente con el system prompt local-first); el usuario ya tiene Docker en su stack; sin cuenta/cloud,
sin dependencia externa. LiveKit Cloud descartado (audio a terceros + cuenta).

### Q2: Cliente que publica el micrófono al room
**[Answer]: El BROWSER del orbe.** En room el worker (agente) solo recibe/responde; algo tiene que
publicar el mic al room. El browser del orbe es la opción más limpia: unifica mic + orbe + audio TTS en
una sola pieza, y da el **orbe sincronizado gratis** (el browser ya recibe el track de voz). Alternativa
(cliente headless Python) descartada: otra pieza sin el beneficio del sync.

### Q3: Dónde corre el wake word "hey saga"
**[Answer]: A DEFINIR en Application Design** (preliminar: el agente escucha el track de audio del room).
Consideración: hoy el wake usa portaudio local en el agente. Con el browser publicando el mic, las opciones
son (a) el wake corre en el browser (Web/onnxruntime-web) sobre el mic local antes de publicar, o (b) el
agente corre el wake sobre el track de audio que recibe del room. Riesgo documentado, se resuelve en diseño.

### Q4: Win+Z (control por teclado)
**[Answer]: SE CONSERVA.** El socket de control (`LK_CTL_SOCK`) sigue: Win+Z manda "press" al agente. Lo
que cambia es de dónde viene el audio (room en vez de console). El flujo de fases (idle/rec/busy) se adapta.

### Q5: Modo console — ¿se elimina o queda como fallback?
**[Answer]: QUEDA como modo dev/fallback.** Room es el default de producción. Console se mantiene para
debug rápido sin servidor (con su limitación conocida del buffer). Selección por flag/env, sin romper nada.

### Q6: Scope de este ciclo
**[Answer]: Migración del transporte (server + worker `start` + browser-cliente) + orbe sync** (consecuencia
natural de que el browser reciba el track). **NO incluye** speaker verification (= Ciclo 5).

## NFR
- **Velocidad (NFR duro vigente)**: no regresar de los ~2-3s actuales. Gate: benchmark en vivo post-migración.
- **Privacidad**: audio local-only (servidor en la propia máquina). No cloud.
- **No romper Win+Z** ni el fallback console.

## Riesgos identificados (a profundizar en Application Design)
1. **Cliente publicador del mic** = pieza nueva (browser publica al room). Es el grueso del trabajo.
2. **Wake word**: repensar dónde corre (browser vs agente-sobre-track).
3. **saga-ctl**: ahora gestiona server + worker (más procesos, más readiness checks).
4. **Latencia WebRTC local**: a medir (esperado despreciable, pero el NFR exige confirmarlo).
5. **Orbe como participante**: el orbe pasa de "solo SSE de estado" a "participante WebRTC del room" — cambio
   no trivial en el orbe (auth con token, suscripción al track, Web Audio).

## Extensiones
Opt-out (Security/Resiliency/PBT = No, heredado). Sin gate bloqueante. (Nota: Security podría reconsiderarse
si el server expone puertos en la red local — evaluar en diseño, no bloqueante ahora.)
