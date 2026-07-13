# Deuda técnica y plan de remediación

Consolidación de la deuda detectada + plan priorizado. **Es un plan, no una ejecución**: no se tocó
código. Detectada durante el análisis del código.

> **Actualización Ciclo 4 (migración console → modo room, 2026-06-23).** La migración resolvió deuda
> que estaba documentada como *limitación de runtime* del modo console (no estaba en la tabla D1-R2 de
> abajo, pero era deuda real). Ver la sección **"Resuelto por el Ciclo 4"**.
>
> **Actualización U7 (modo único room, 2026-06-23).** El refactor U7 **eliminó el transporte console y
> el flujo clásico standalone** (`vc/app.py:_do_turn`, `whisper_daemon.py`, `vc/audio.py`/`stt.py`/`tts.py`,
> env `VOICE_LIVEKIT`/`SAGA_TRANSPORT`/`VOICE_WAKE_ENABLED`/`VOICE_AUTOSTOP`). Esto **cerró D1 de raíz**:
> ya no hay lógica de turno duplicada (`lk/claude_llm.py` es el único turn handler). Ver D1 abajo.
>
> **Actualización U8 (dispatch consistente).** El Win+Z `FileNotFoundError` intermitente ("coin-flip"
> del dispatch) quedó **RESUELTO**. Causa raíz real: el worker corría en modo prod con `load_threshold=0.7`
> y se auto-marcaba `unavailable` cuando la CPU local cruzaba 0.7 durante el arranque (load-shedding de
> *pools* aplicado a un worker single-tenant) → el dispatch caía en esa ventana → 503. NO era un "server
> envenenado" ni pestañas zombie. Fix (4 cambios nativos de livekit-agents 1.6): `load_fnc=0` (worker
> siempre disponible) + dispatch AUTOMÁTICO (`@server.rtc_session()` sin `agent_name`, se eliminó
> `_ensure_agent_dispatched()` de `vcctl.py` y `LIVEKIT_AGENT_NAME` de `vc/config.py`) + server/worker
> relanzados frescos en cada `start` + `close_on_disconnect=False` (recargar la pestaña no mata el socket
> de Win+Z). El viejo diagnóstico del "cold-start 503 / probe `list_dispatch` / retry de 90s" quedó
> OBSOLETO (era erróneo).

## Resuelto por el Ciclo 4 (migración a modo room)

Deuda/limitaciones del modo console que el cambio de transporte **eliminó de raíz** (verificado en vivo
por el usuario, 10/10). Referencia: `aidlc-docs/construction/build-and-test/ciclo4-build-and-test.md`.

| # | Deuda (modo console) | Cómo se resolvió en room | Estado |
|---|---|---|---|
| C-buffer | **Buffer de audio acumulado en idle**: en console `set_audio_enabled(False)` no detenía la captura → el `rtc.AudioStream` (C++) acumulaba backlog (medido 121s/72s/etc.) → STT transcribía ruido fantasma, flujo roto. Era OPACO (no purgable desde Python); el Ciclo 3 lo cerró como diagnóstico sin fix. | En room el track del cliente se **detacha** físicamente con el mic apagado → los frames se descartan (no hay backlog). | ✅ Resuelto |
| C-away | **Away timer sobre método privado de LiveKit**: el away usaba `user_away_timeout` nativo + `session._set_user_away_timer()` (internal), y disparaba "no entendí" a los 0s (timer stale). | Reemplazado por un timer **propio** `asyncio.call_later`, VAD-aware (arma en Win+Z, cancela al `speaking`/`thinking`). Sin internals de LiveKit. | ✅ Resuelto (deuda saldada) |
| C-orbe | **Orbe sin sync con la voz real**: documentado como "imposible" en console (audio en un proceso, dibujo en otro, sync fino sobre HTTP inviable). Estaba como backlog futuro (Electron/Tauri o browser-participante). | El modo room lo desbloqueó: el browser es participante del room, recibe el track TTS y mide el nivel real con Web Audio `AnalyserNode` (U5). El orbe late con la voz real. | ✅ Resuelto (no es más deuda) |

## Resumen de la deuda

| # | Ítem | Dónde | Severidad |
|---|------|-------|-----------|
| D1 | Lógica de turno **duplicada** clásico vs LiveKit | `vc/app.py:_do_turn` y `lk/claude_llm.py` | ✅ Resuelta (U7) |
| P1 | Path de Win+Z = **glue propio** (socket Unix + SSE), no primitiva LiveKit | `lk/agent.py` + `orb/orb_server.py` | Baja (pulido) |
| P2 | Volumen de la respuesta **baja** en call de voz (echo-cancellation ducking del browser) | cliente orbe (`orb.html`) | Baja (pulido) |
| P3 | Ruido de fondo: **BVC es Cloud-only**; en self-hosted no se usa (room se apoya en VAD Silero) | `lk/agent.py` | Baja (evaluar) |
| D2 | Sin lint / typecheck / CI | repo | ✅ Resuelta (Ciclo 9 / U1: ruff + mypy + pip-audit en CI) |
| D3 | LiveKit **sin pin** en `pyproject.toml` | `pyproject.toml` | Media |
| D4 | `is_goodbye` huérfana (código muerto testeado) | `vc/session.py` + `tests/test_pure.py` | ✅ Resuelta (removida) |
| D5 | `import os` duplicado | `vc/app.py` | ✅ Resuelta (U7 reescribió `vc/app.py`) |
| D6 | Sin tests en `lk/*`, `claude_daemon.py`, `vcctl.py`, `vc/claudecli.py`, `vc/runtime.py` (mocks pesados) | esos módulos | Baja (declarada en Ciclo 9 / U1) |
| D7 | `pip-audit` en CI audita solo el lock curado (44 deps directas), no el cierre transitivo completo | `.github/workflows/tests.yml` | Baja (declarada en Ciclo 9 / U1) |
| R1 | Hardening de seguridad puntual (recomendación) | god-mode, sockets, secretos | En curso (Ciclo 9: U2 orb_server + U3 permisos) |
| R2 | Adoptar **PBT** (Hypothesis) | funciones puras | ✅ Resuelta (Ciclo 9 / U1: PBT full, P1-P10) |

## Plan priorizado

Orden sugerido por relación impacto/esfuerzo/riesgo. Todo es reversible y de bajo riesgo.

### 1. D5 — `import os` duplicado — ✅ RESUELTA
- **Resolución**: el refactor U7 reescribió `vc/app.py` (hoy 40 líneas, emisor del `press` + `--doctor`);
  ya no contiene ningún `import os`. La deuda desapareció con la reescritura, no requiere acción.

### 2. D4 — `is_goodbye` huérfana — ✅ RESUELTA
- **Resolución**: `is_goodbye` y sus tests fueron eliminados (`rg is_goodbye vc/ tests/` = 0). Ya no
  hay código muerto que decidir; el limbo se cerró.

### 3. D3 — Pin de LiveKit
- **Impacto**: reproducibilidad / evitar romper en upgrades. **Esfuerzo**: bajo. **Riesgo**: bajo.
- **Acción**: fijar un rango mínimo razonable de `livekit-agents` (+ plugins) en `pyproject.toml`,
  consistente con el lock de `requirements.txt`. (Respetar la convención del repo de no pinear
  versiones viejas de memoria: usar la que ya resolvió el lock.)

### 4. D2 — Lint / typecheck / CI
- **Impacto**: sostiene la calidad sin depender de disciplina manual. **Esfuerzo**: medio. **Riesgo**: bajo.
- **Acción**: agregar `ruff` (lint) + opcional `mypy` sobre los módulos puros; un workflow mínimo
  que corra `py_compile` + `ruff` + `tests/test_pure.py`. Empezar permisivo para no frenar el repo.

### 5. R2 — PBT-partial (Hypothesis)
- **Impacto**: tests más fuertes sobre la lógica de decisión. **Esfuerzo**: medio. **Riesgo**: bajo.
- **Acción**: agregar `hypothesis` y propiedades sobre funciones puras, por ejemplo:
  - `guard.denied` bloquea siempre cualquier variante de los patrones catastróficos.
  - `attach.take_staged` cumple consume-once (segunda llamada → vacío).
  - `is_reset_command` / `is_visual_command` respetan word boundaries (no matchean substrings).

### 6. R1 — Hardening de seguridad puntual
- **Impacto**: reduce superficie de riesgo (god-mode + voz). **Esfuerzo**: variable. **Riesgo**: medio (cambia comportamiento).
- **Acción** (evaluar, no automático):
  - Revisar/expandir la denylist de `vc/guard.py` contra nuevos comandos catastróficos.
  - Confirmar perms `0o600` en todos los artefactos sensibles (wav, screenshot, log, sockets) — ya está, mantener.
  - Considerar un modo "no god" más usable para sesiones de riesgo (`VOICE_CLAUDE_SAFE=1` ya existe).

### 7. D1 — Duplicación clásico/LiveKit — ✅ RESUELTA (U7)
- **Impacto (histórico)**: alto a largo plazo (drift: un comando de voz había que cablearlo en dos lados).
- **Resolución**: el refactor U7 **eliminó el flujo clásico standalone** (`vc/app.py:_do_turn`,
  `whisper_daemon.py`, `vc/audio.py`/`stt.py`/`tts.py`) en vez de extraer un núcleo común. Ya no hay
  duplicación: `lk/claude_llm.py` es el **único** turn handler. `vc/app.py` quedó como emisor del `press`
  de Win+Z + `--doctor`. El drift que documentaba `CLAUDE.md` desapareció.

## Deuda de pulido del modo room (Ciclo 4) — baja prioridad

Anotada en Build & Test del Ciclo 4 como **pulido, no blocker**. El sistema anda 10/10 sin esto.

### P1 — Win+Z = glue propio (socket Unix + SSE)
- **Impacto**: el control de Win+Z (press/say/stage) viaja por un socket Unix + el orbe lee estado por
  SSE; no usa una primitiva nativa de LiveKit. Funciona, pero es código a mantener fuera del framework.
- **Acción** (revisable): evaluar mover el control a un **data channel / RPC** de LiveKit (o full
  client-side cuando se haga U4). No urgente.

### P2 — Volumen de respuesta bajo (echo-cancellation)
- **Impacto**: en call de voz el browser hace ducking por echo-cancellation y baja el volumen del TTS.
- **Acción** (ajustable): tunear las constraints de audio del cliente (`orb.html`). Bajo esfuerzo.

### P3 — Ruido de fondo / BVC Cloud-only
- **Impacto**: `noise_cancellation.BVC()` requiere LiveKit Cloud; en self-hosted está gateado a console.
  En room no hay cancelación de ruido del lado del agente.
- **Acción** (evaluar): si el ruido molesta, considerar `ai_coustics` (alternativa self-host). No
  aplicado todavía.

## Latencia (NFR — no es regresión)

El benchmark del Ciclo 4 (104 turnos reales, 2026-06-23) confirmó **sin regresión** de latencia con el
cambio console → room (procesamiento real ≈ 2.5s, en línea con el baseline). El cuello que **queda** no
es del transporte: **claude-mem corre hooks de memoria ~2s por turno** (más los picos de consultas
pesadas a Claude). No es deuda nueva del Ciclo 4; es el techo de latencia conocido del cerebro.

## Features diferidas (no deuda)

- **U4 — wake "hey saga" en el cliente** (`onnxruntime-web`): DIFERIDO al final del Ciclo 4 y no
  ejecutado (port más caro: cliente vs server-on-track). El modelo `hey_saga.onnx` (FPPH=0) ya existe;
  hoy el trigger es Win+Z. Pendiente de retomar.

## Ciclos futuros (decisiones de producto, no deuda)

- **Ciclo 5 — saga agéntico** (ARRANCADO, spike): darle "manos" (tools/MCPs). Primer paso ya dado en
  Ciclo 4 (prompt que habilita el Bash built-in). El spike agregó el toggle `CLAUDE_PLUGINS=1`: carga los
  plugins de Claude (MCP+skills+hooks+slash) en el `claude_daemon` caliente, menos una blacklist editable
  (`configs/plugins-blacklist.json`, aislada en `.saga-settings.json` sin tocar `~/.claude`). Default OFF
  (claude pelado = más rápido). Costo medido: los turnos con tool/MCP tardan 13-17s+ (tool-defs en contexto +
  round-trips) → el watchdog `_busy` subió a 60s. La latencia agéntica es cuestión de Claude, no del harness.
- **Ciclo 6 — speaker verification** ("solo mi voz"): DIFERIDO. No arrancado.

## Criterio transversal
Cualquier ejecución de este plan debe terminar con verificación proporcional (`py_compile` +
`tests/test_pure.py` + prueba en vivo del Win+Z cuando toque el flujo), y commit solo con
confirmación explícita.
