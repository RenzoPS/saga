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
> siempre disponible) + dispatch automático + server/worker relanzados frescos en cada `start` +
> `close_on_disconnect=False` (recargar la pestaña no mata el socket de Win+Z). El viejo diagnóstico
> del "cold-start 503 / probe `list_dispatch` / retry de 90s" quedó OBSOLETO (era erróneo).
>
> **Actualización**: el dispatch automático **también se descartó**. Despacha al *crearse* el room, y
> con la pestaña del orbe abierta el cliente reconectaba ~2s antes de que el worker terminara de
> registrarse (medido: room 00:32:41.106, worker 00:32:43.226) → `saga-ctl restart` fallaba **siempre**.
> Hoy el dispatch va **por API** desde `/token` (`vc/dispatch.py`), que pide el agente cuando el cliente
> está por entrar. El camino "elegante" del JWT (`RoomConfiguration.agents`) tampoco sirve: pide un job
> `JT_PARTICIPANT` y el SDK de Python solo registra `JT_ROOM`/`JT_PUBLISHER`. Hay un test canario.

## Resuelto por el Ciclo 4 (migración a modo room)

Deuda/limitaciones del modo console que el cambio de transporte **eliminó de raíz** (verificado en vivo
por el usuario, 10/10).

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
| P2 | Volumen de la respuesta **baja** de la nada | cliente orbe (`orb.html`) | ✅ Resuelta — no era ducking: `attachRemoteAudio` solo appendeaba, y con `close_on_disconnect=False` cada `saga-ctl restart` sumaba otro `<audio>` sobre el MISMO track. Dos pipelines de playback con jitter buffers independientes → interferencia destructiva. Ahora cada attach limpia el anterior |
| P3 | Ruido de fondo: **BVC es Cloud-only**; en self-hosted no se usa (room se apoya en VAD Silero) | `lk/agent.py` | Baja (evaluar) |
| D2 | Sin lint / typecheck / CI | repo | ✅ Resuelta (Ciclo 9 / U1: ruff + mypy + pip-audit en CI) |
| D3 | LiveKit **sin pin** en `pyproject.toml` | `pyproject.toml` | Media |
| D4 | `is_goodbye` huérfana (código muerto testeado) | `vc/session.py` + `tests/test_pure.py` | ✅ Resuelta (removida) |
| D5 | `import os` duplicado | `vc/app.py` | ✅ Resuelta (U7 reescribió `vc/app.py`) |
| D6 | Sin tests en `lk/*`, `claude_daemon.py`, `vcctl.py`, `vc/claudecli.py`, `vc/runtime.py` (mocks pesados) | esos módulos | Baja (declarada en Ciclo 9 / U1) |
| D7 | `pip-audit` en CI audita solo el lock curado (44 deps directas), no el cierre transitivo completo | `.github/workflows/tests.yml` | Baja (declarada en Ciclo 9 / U1) |
| **D8** | **Interrumpir mata el proceso de Claude** → el turno siguiente paga un `--resume` en frío | `claude_daemon.py` (`kill()` en el cancel) | **Alta** |
| **D9** | La sesión de Claude **no expira**: crece sin límite hasta un reset por voz | `vc/session.py` | Media |
| D10 | El modo (`SAGA_MODE`) **no es pegajoso**: sale del env, un `restart` te devuelve a ptt en silencio | `vc/config.py` + `vcctl.py` | Media |
| D11 | `metrics_collected` deprecado (muere en v2.0). El reemplazo para latencias es `ChatMessage.metrics`, que vive en el `chat_ctx` que `claude_llm` no llena | `lk/agent.py` | Baja |
| **D12** | **`wake_daemon.py` es código muerto**: nadie lo levanta (154 líneas + modelo Vosk en disco) | `wake_daemon.py`, `vcctl.py`, `vc/config.py` | **Media** (borrado, riesgo cero) |
| D13 | Wake word completo: OFF por default y con falsos positivos medidos (confianza 0.11–0.12) | `lk/wakeword.py`, `lk/onnx_tune.py`, `scripts/*wakeword*` | Baja (producto) |
| D14 | Fallbacks sin Deepgram: solo corren sin key | `lk/whisper_stt.py`, `lk/edge_tts_plugin.py` | Baja (producto) |

### D8 — el costo real de interrumpir (medido)

`claude_daemon.py` mata el grupo de procesos entero cuando cancelás un turno en curso, porque no
teníamos forma de decirle al CLI "abortá". Medido sobre 329 turnos de log real:

| Situación | ttft (mediana) |
|---|---|
| proceso caliente, sin tools | **1.67s** |
| turno que usa tools | 3.69s |
| turno después de un respawn | **5.98s** |

Y midiendo el arranque en frío contra una copia de la sesión real (823 mensajes / 816 KB):

| | primer token |
|---|---|
| spawn fresco, sesión vacía | 4.17s |
| spawn + `--resume` de 823 mensajes | 5.53s |

O sea: de los ~3.9s que cuesta una interrupción, **~2.5s son levantar el proceso** y ~1.4s recargar
la sesión. El tamaño de la conversación (D9) es el término menor.

**El camino está identificado**: el binario del CLI expone `subtype:"interrupt"` en su protocolo de
control, sobre el mismo stdin que ya usamos con `--input-format stream-json` — el mismo que usa
`interrupt()` del Agent SDK. Abortar el turno sin matar el proceso es posible y no está hecho.
Arreglar D8 vuelve a D9 casi irrelevante, porque desaparecen las recargas.
| R1 | Hardening de seguridad puntual (recomendación) | god-mode, sockets, secretos | En curso (Ciclo 9: U2 orb_server + U3 permisos) |
| R2 | Adoptar **PBT** (Hypothesis) | funciones puras | ✅ Resuelta (Ciclo 9 / U1: PBT full, P1-P10) |

## D12–D14 — Tamaño del código: qué es peso propio y qué es grasa

Auditoría medida el 22/8, disparada por una comparación honesta: `saga-gemini` (el banco de pruebas
con LLM en la nube) resuelve una conversación completa en **94 líneas y un solo `.py`**. saga tiene
**4868**. La pregunta —"¿cuánto de esto es basura nuestra?"— merecía números.

### Lo primero: 32% no es código

| | líneas |
|---|---|
| código real | **2939** |
| comentarios | 766 |
| docstrings | 646 |

El proyecto documenta las decisiones caras en el lugar donde se leen. Eso es deliberado y no es deuda.

### Lo segundo: dónde vive cada línea

| Grupo | líneas | ¿lo resuelve LiveKit/Deepgram? |
|---|---|---|
| **Claude Code** — daemon, CLI, turno segmentado, `heard`, guard, sesión | 1205 | **No.** No hay camino oficial para embeber una IA agéntica |
| **Features que `saga-gemini` no tiene** — orbe, `saga-ctl`, hotkey, adjuntos, dispatch, doctor | 1095 | No. Es producto, no cableo |
| Wake word | 439 | Parcial: usa el `WakeWordModel` oficial; la ventana es propia |
| Fallback sin key de Deepgram | 91 | No existe alternativa nativa |
| Config + cableo del agente | 750 | Es el pegamento |

**La comparación con `saga-gemini` no es justa**: 94 líneas alcanzan porque no tiene hotkey, ni orbe,
ni capturas, ni adjuntos, ni wake, ni guard, ni orquestación, ni daemon, ni tests, ni fallback offline
— y su `web/` es el starter de Next.js de LiveKit sin modificar. La distancia **no la hace la grasa**:
la hacen los 1205 de Claude Code y los 1095 de features que el otro proyecto no tiene.

### Lo tercero: la grasa que sí existe

| # | Ítem | Líneas | Severidad |
|---|------|--------|-----------|
**D12 — `wake_daemon.py` es código muerto (154 líneas).** Nadie lo levanta: las 4 referencias que
aparecen son `saga-ctl status` imprimiendo *"— (Vosk dormido, fuera de scope)"*. Un daemon que solo
existe para que el status diga que está dormido. Arrastra `SAMPLE_RATE` en `vc/config.py`, su entrada
en `DAEMONS` + el caso especial de `vcctl.py`, y el modelo de Vosk en disco. Borrado de riesgo cero.

**D13 — Wake word completo (439 líneas).** `SAGA_WAKE_ENABLED=0` por default, y prendido genera falsos
positivos: en el log del 22/8 hay detecciones con confianza **0.11 / 0.12** que el agente tiene que
ignorar explícitamente para que no corten la llamada. `lk/onnx_tune.py` existe **solo** porque el wake
quemaba ~367% de CPU en idle. Efecto lateral: con el wake ON el mic del browser queda desmuteado
siempre, lo que hoy es lo único que hace andar el modo llamada (el gate por estado solo desmutea en
`rec`, que en llamada no ocurre nunca).

**D14 — Fallbacks sin Deepgram (91 líneas).** `whisper_stt` + `edge_tts_plugin` solo corren sin
`DEEPGRAM_API_KEY`. Se quedan si querés que saga funcione offline; si no, son dos ramas de `if` y un
modelo de whisper en disco.

**Recorte posible: ~684 de 2939 = 23%.** Y el punto incómodo: borrar todo eso deja saga en ~2255
líneas contra 94. **No acorta la distancia** — solo saca peso muerto, que igual vale la pena.

### Lo que sí acorta la distancia

Las ~500 líneas de `lk/speech.py` + `lk/heard.py` + buena parte de `lk/claude_llm.py` existen **solo
porque rompemos el contrato del framework** (ver "Quién es dueño del contexto" en
[`architecture.md`](architecture.md)). Si el contexto pasa a ser de LiveKit y Claude Code baja de
"cerebro" a `@function_tool`:

- `heard.py` desaparece — la truncación al interrumpirte es nativa
- `speech.py` desaparece — el hueco de tools deja de ser un stream roto y pasa a ser una tool que
  tarda, caso que el framework cubre con [async tools](https://docs.livekit.io/agents/logic/tools/async/)
  (`ctx.update()` para el progreso, `ctx.with_filler()` para el silencio, verificados en 1.6.10)
- D8 (respawn) y D9 (sesión sin límite) dejan de existir por construcción

**Costo real**: Claude arranca sin memoria de su propio trabajo agéntico entre turnos — el `chat_ctx`
de LiveKit solo guarda texto hablado, no qué comandos corrió. Medido sobre 329 turnos: **4.6% usan
tools** (15 turnos, 164 llamadas). Los otros 314 pagan hoy el precio de una arquitectura que solo
esos 15 necesitan.

Esto es una **decisión de producto pendiente**, no una tarea. Ver "Ciclos futuros".

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
  - ✅ RESUELTO (Ciclo 9 / U3): se fue el god-mode. Hoy `--permission-mode auto` (incondicional, sin toggle:
    `VOICE_CLAUDE_SAFE` se eliminó) + guard fail-closed con parser (los bypasses `rm -r -f` se cerraron)
    + confirmación hablada de dos pasos en el system prompt.

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
- **Quién es dueño del contexto**: hoy Claude Code (`--resume`); la alternativa nativa es que lo sea
  LiveKit y que Claude baje a `@function_tool` + [async tools](https://docs.livekit.io/agents/logic/tools/async/).
  Se van ~500 líneas (`speech.py`, `heard.py`, parte de `claude_llm.py`) y D8/D9 dejan de existir por
  construcción. Se pierde la memoria del trabajo agéntico entre turnos. **4.6% de los turnos usan
  tools** (medido sobre 329). Decisión pendiente — ver D12–D14 arriba.

> **Nota de numeración**: los ítems de seguridad del Ciclo 9 / U3 son **S1** y **S2** (abajo). Antes se
> los llamaba D8 y D9; se renombraron para no chocar con los D8–D14 del resumen.

### S1 — El guard loguea el comando bloqueado (Ciclo 9 / U3)
- **Qué**: cuando el guard deniega, escribe el comando a `stderr` (queda en el log del hook). Ese comando
  podría traer un secreto en la línea (ej. `curl -H "Authorization: ..."`).
- **Impacto**: bajo. **No empeora nada de lo actual**: `saga.log` ya guarda el transcript completo del turno.
  Se registra para no perderlo de vista si algún día se endurece el manejo de logs (SECURITY-03).

### S2 — Sandbox real de ejecución (bubblewrap / firejail / seccomp)
- **Qué**: hoy la defensa vive en la capa del **modelo** (permission-mode + system prompt) y en un **hook**
  (guard). La guía de Anthropic citada en la investigación del ciclo dice lo contrario: *"containment en la capa
  de entorno primero, comportamiento del modelo después"*.
- **Por qué no se hizo en U3**: cambia la arquitectura de ejecución entera (cómo se spawnea `claude`, qué ve del
  filesystem). Es **otro ciclo**, no un ítem de esta unidad. Es la respuesta correcta a un modelo de amenaza más
  duro que el que el usuario eligió (mishears/accidentes, no atacante activo con acceso local).

## Criterio transversal
Cualquier ejecución de este plan debe terminar con verificación proporcional (`py_compile` +
`tests/test_pure.py` + prueba en vivo del Win+Z cuando toque el flujo), y commit solo con
confirmación explícita.
