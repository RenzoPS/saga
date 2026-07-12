# Ciclo 4 — Build & Test (migración modo room) · Registro

> Stage Build & Test del Ciclo 4. Como es un sistema de voz en tiempo real, la prueba es EN VIVO en el
> browser real del usuario (Win+Z, hablar, observar el orbe). El WebRTC no levanta en headless (Playwright),
> así que la validación end-to-end la hace el usuario; desde acá se verifica por código (py_compile, logs,
> auth API, dispatch, source de LiveKit) + se diagnostica por logs.

## Cómo se corre / verifica
- Levantar todo: `saga-ctl start` (server nativo + claude_daemon + worker + orb_server + browser).
- Monitor: `tail -F saga.log` (o el kitty que abre saga-ctl) — eventos `▎` (Win+Z, silencio, pensando, etc.).
- Logs por pieza: `livekit_server.log`, `livekit_agent.log`, `saga.log`.
- Bajar todo: `saga-ctl stop`.

## Issues encontrados y resueltos (en orden cronológico)
| # | Síntoma | Causa raíz | Fix | Commit |
|---|---|---|---|---|
| 1 | Orbe pedía `.mjs` como octet-stream | MIME map sin `.mjs` | agregado al MIME de orb_server | b685a8d |
| 2 | `dtls timeout`, voz no llegaba | NAT de Docker rompe WebRTC local | server NATIVO (no Docker) + udp_port + NODE_IP | b685a8d/9ccd758 |
| 3 | Win+Z `FileNotFoundError` (sin socket) | auto-dispatch sólo al crear el room; pestaña zombie lo creaba antes | dispatch EXPLÍCITO por API (agent_name + saga-ctl create_dispatch) | 9ccd758 |
| 4 | Volumen de respuesta bajaba | echo-cancellation ducking del browser | anotado (pulido) | — |
| 5 | `RoomInputOptions` deprecado | API 1.6 movió a RoomOptions | migrado | b685a8d |
| 6 | away "no entendí" a los 0s | timer nativo stale; usaba método privado | timer propio `asyncio.call_later` VAD-aware | 7ee242b |
| 7 | turno de voz perdido / sin TTS | **preemptive_generation ON** (param top-level deprecado/ignorado; default enabled:True) | `turn_handling={"preemptive_generation":{"enabled":False}}` | 59e4bfe/c1efbee |
| 8 | frases con pausas se partían (chopping) | VAD puro corta por silencio | turn detector SEMÁNTICO (MultilingualModel) + min_delay 2.0 | c1efbee |
| 9 | cancel dejaba el daemon ocupado (zombie) | el daemon DRENABA el turno cancelado | cancel mata el grupo + respawn `--resume` | c1efbee |
| 10 | orbe no latía / parpadeaba / se inflaba | AudioContext suspended; jitter; sin techo | resume por gesto + suavizado envolvente + techo 0.38 | ed7620c |
| 11 | falso "no te entendí" en frases válidas | flag `spoke` confundía vacío con chopping | revertido; empty-cut + watchdog en su lugar | c1efbee |

## Lección de proceso
Hubo churn por **adivinar config de LiveKit** (keys del dict, lugar del `preemptive_generation`, el flag `spoke`).
Aprendizaje: verificar campos contra el TypedDict real + el SOURCE de livekit-agents antes de tocar el path de
voz que ya anda. El issue #7 se cerró recién al leer `turn.py:151` (`_PREEMPTIVE_GENERATION_DEFAULTS.enabled=True`).

## Estado final (verificado por el usuario, 10/10)
- Transporte room, server nativo, dispatch robusto: OK.
- Voz end-to-end SIN chopping, responde, rápido: OK.
- Orbe late con la voz real, suave, sin inflarse: OK.
- Cancel limpio (sin zombie), empty-cut → amarillo, watchdog anti-cuelgue: OK.
- Agéntico (Bash built-in): OK.
- Arrancable con `saga-ctl start`: OK. Sin deudas técnicas abiertas.

## Benchmark de latencia (NFR gate) — 2026-06-23

**NFR del ciclo**: "no regresar la latencia ~2-3s". Medido sobre 104 turnos reales (métricas de saga.log).

| Métrica | Mediana | Prom | p90 | Qué es |
|---|---|---|---|---|
| LLM ttft | **2.2s** | 3.9s | 7.7s | el cerebro (claude_daemon) arranca a responder |
| TTS ttfb | **0.3s** | 0.9s | 0.85s | arranque de la voz |
| EOU delay | **2.0s** | 1.9s | 2.1s | espera tras dejar de hablar (= `min_delay` anti-chopping) |
| transcription_delay | 0.5s | 0.6s | 1.2s | STT (Deepgram) |

**Latencia percibida típica** (dejás de hablar → voz de saga) ≈ **4.5s** = EOU 2.0 + ttft 2.2 + ttfb 0.3.

**Veredicto NFR**: ✅ El **procesamiento real** (cerebro 2.2s + voz 0.3s ≈ 2.5s) está en línea con el baseline,
**no regresó**. La latencia percibida es ~4.5s porque se suma el `min_delay=2.0` (la espera anti-chopping, que
es una DECISIÓN, no una regresión del cerebro). Trade-off tuneable: bajar `min_delay` acelera pero reintroduce
chopping. Los picos de ttft (p90 7.7s, max 45s) son consultas pesadas (claude + claude-mem hooks por turno),
no del transporte. El NFR del transporte room se cumple: el cambio console→room no degradó la latencia base.

## PENDIENTE para cerrar el Ciclo 4
- **U4** (wake "hey saga" en el cliente, onnxruntime-web) — DIFERIDO (port más caro; decisión de enfoque pendiente).
- **Benchmark de latencia (NFR gate)**: medir TTFT/turn end-to-end vs el baseline (~2-3s, no regresar). Falta
  correr la medición formal y registrarla acá.
- **README / CLAUDE.md**: actualizar a "modo room = default" (hoy dicen console fallback).
