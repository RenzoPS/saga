# U8 — Dispatch consistente — Code Generation Plan

> AI-DLC · CONSTRUCTION · Code Generation (Part 1: Planning). Brownfield. Unidad de hardening del
> transporte room (Ciclo 4). **Fuente de verdad técnica: `../U8-dispatch-consistente/functional-design.md`.**
> Este plan es la versión EJECUTABLE numerada de esos 4 cambios. Single source of truth para Code Generation.

## Contexto de la unidad
- **Objetivo**: matar de raíz el "coin-flip del dispatch" (Win+Z `FileNotFoundError`/`ConnectionRefusedError`
  intermitente en `saga-ctl start`). Causa raíz MEDIDA: worker en modo prod con `load_threshold=0.7` →
  se auto-marca `unavailable` cuando la CPU local cruza 0.7 → `create_dispatch` cae en esa ventana → `503`.
- **Dependencias**: ninguna unidad nueva. Toca el transporte room ya entregado (U1/U2/U6).
- **Sin lógica de negocio / API / repo / frontend / DB / migraciones**: es transporte+orquestación.
  Por eso el plan NO sigue las capas business/API/repo del template (N/A); usa pasos por archivo + verificación.
- **Descartes explícitos** (el functional-design los marca como parches a tirar): el gate `list_dispatch`
  (paso 3.5, ya eliminado en working tree) y el retry de 90s en `_ensure_agent_dispatched` (working tree
  actual). NO se commitean: U8 elimina la función entera.

## Archivos afectados (todos brownfield = MODIFICAR in-place, nunca duplicar)
| # | Archivo | Cambios |
|---|---|---|
| 1 | `lk/agent.py` | C1 `load_fnc=lambda:0.0` + `drain_timeout=0` + `num_idle_processes=1` · C2 `@server.rtc_session()` sin agent_name + `pop` env defensivo + quitar import `LIVEKIT_AGENT_NAME` · C4 `room_input_options=RoomInputOptions(close_on_disconnect=False)` en `session.start` |
| 2 | `vcctl.py` | C2 eliminar `_ensure_agent_dispatched()` + su llamada (paso 4.5) · C3 `_start_room`: server+worker SIEMPRE frescos (bajar viejos→relanzar), conservar dedup de claude/orb, reordenar (browser ANTES del wait-socket) |
| 3 | `vc/config.py` | C2 eliminar `LIVEKIT_AGENT_NAME` (queda sin uso) |
| 4 | docs | `.claude/CLAUDE.md` + `docs/*.md` + comentario `orb/orb_server.py`: pasar a "auto-dispatch nativo"; borrar la desinformación de dispatch explícito / `list_dispatch` / cold-start envenenado / retry-90s |

---

## Pasos

### Step 0 — Higiene del working tree (partir limpio) `[x]`
- [x] `tests.yml` (reindent + bumps `checkout@v7`/`setup-python@v6` espurios, no documentados): revertir
      `git checkout .github/workflows/tests.yml`. NO es parte de U8.
- [x] `vcctl.py` retry-90s: NO revertir aparte — queda subsumido en Step 2 (se elimina la función entera).
- [x] Verificar baseline: `py_compile` OK + `tests.test_pure` verde ANTES de empezar (sanity del punto de partida).

### Step 1 — `lk/agent.py` (Cambios 1, 2, 4) `[x]`
- [x] **C1**: `server = AgentServer(load_fnc=lambda: 0.0, drain_timeout=0, num_idle_processes=1)`.
  - `load_fnc=0` → worker dedicado single-tenant nunca cruza `load_threshold` → permanece `available` →
    el dispatch siempre lo encuentra (mata el coin-flip). `load_fnc` es param público (`worker.py:326`),
    invocado con o sin arg vía `inspect.signature` (`worker.py:1270-1281`) → lambda sin args es válida.
    Respetado en self-hosted (sólo se ignora en LiveKit Cloud, `worker.py:575-583`). Bonus eficiencia:
    con `load_fnc` custom el SDK NO arranca el thread monitor de CPU (`worker.py:575`).
  - `drain_timeout=0` → al SIGTERM el worker cierra al toque (hoy entra en "draining 1800s" y ocupa :8081,
    bloqueando el próximo start).
  - `num_idle_processes=1` (EFICIENCIA) → el prod_default es 8 (`worker.py` ServerEnvOption): en modo `start`
    el SDK pre-forkea 8 procesos que re-importan agent.py con los plugins (deepgram/silero/turn_detector) →
    ~7 procesos Python de más en RAM + pico de CPU de arranque (que alimentaba el load_threshold). saga
    atiende 1 turno a la vez → 1 proceso caliente alcanza. Param público del `AgentServer`.
- [x] **C2**: `@server.rtc_session()` SIN `agent_name` → dispatch automático nativo. Defensa: antes de crear
      el server, `os.environ.pop("LIVEKIT_AGENT_NAME", None)` (el SDK fuerza explicit dispatch si esa env
      existe — `worker.py:517`). Quitar `LIVEKIT_AGENT_NAME` del import de `vc.config` (línea 47).
- [x] **C4**: `session.start(agent=Assistant(), room=ctx.room, room_input_options=RoomInputOptions(close_on_disconnect=False))`.
      Al recargar/cerrar la pestaña la sesión NO se cierra → el job sigue vivo → el socket Win+Z persiste →
      mata el `ConnectionRefusedError`. Verificar el import correcto de `RoomInputOptions` (de `livekit.agents`).
- [x] Smoke estático del paso: `py_compile lk/agent.py`.

### Step 2 — `vcctl.py` (Cambios 2, 3) `[x]`
- [x] **C2**: eliminar `_ensure_agent_dispatched()` completa (210-270) y su llamada (paso 4.5, 377-386).
      saga-ctl ya NO despacha por API: el browser, al unirse al room "saga", lo crea → el server
      auto-despacha el worker → `entry()` corre → socket. Sacar imports/refs muertas que queden.
- [x] **C3 — server+worker SIEMPRE frescos**: en `_start_room`, reescribir la lógica "YA corría" de
      server y worker → bajarlos (si hay) y relanzarlos frescos (reusar el matar-por-pid-exacto de `stop`,
      SIGTERM→SIGKILL, sin tocar el `claude` de esta sesión). Server fresco = rooms en memoria reseteados =
      sin zombies → el 1er browser crea el room limpio → auto-dispatch garantizado. **Conservar** el
      dedup-safe de `prewarm_claude()` + `ensure_orb()` (procesos sanos y caros; se reusan).
- [x] **C3 — reordenar**: abrir el browser (xdg-open, paso 5) ANTES del `_wait_ready` del socket; el
      `_wait_ready(LK_CTL_SOCK)` pasa a ser el último paso (readiness REAL: el agente entró por la vía del
      browser). Quitar el "abrir browser sólo después del dispatch".
- [x] Smoke estático: `py_compile vcctl.py` + grep refs muertas (`_ensure_agent_dispatched`, `create_dispatch`,
      `list_dispatch`, `LIVEKIT_AGENT_NAME`) = 0.

### Step 3 — `vc/config.py` (Cambio 2) `[x]`
- [x] Eliminar `LIVEKIT_AGENT_NAME = os.environ.get(...)` (línea 174). Confirmar 0 importadores tras Steps 1-2.

### Step 4 — Documentación (Cambio 4) `[x]`
- [x] `.claude/CLAUDE.md`: reescribir los gotchas de dispatch (sección "Gotchas modo ROOM"): de "dispatch
      EXPLÍCITO por saga-ctl" → "dispatch AUTOMÁTICO nativo (browser crea el room → server auto-despacha)".
      Borrar el gotcha extenso de cold-start/`list_dispatch`/503-perpetuo (queda obsoleto: ya no hay
      dispatch por API). Agregar gotcha nuevo: `load_fnc=0` (por qué el worker single-tenant no usa
      load-shedding) + `close_on_disconnect=False` (socket Win+Z sobrevive recarga) + server+worker frescos.
- [x] `docs/*.md` (architecture, internal-api, code-guide, operations, turn-flow): alinear a auto-dispatch.
- [x] `orb/orb_server.py`: actualizar el comentario de `/token` si menciona dispatch (no cambia código:
      ya sólo mintea JWT con room_join).

### Step 5 — Resumen de generación `[x]`
- [x] Escribir `aidlc-docs/construction/U8-dispatch-consistente/code/generation-summary.md`: archivos
      modificados (con distinción modificado/eliminado), qué cambió por cambio (C1-C4), y resultados de
      verificación estática. Sin instrucciones de workflow.

---

## Verificación (Build & Test la ejecuta formalmente; acá se deja lista)
- `py_compile` de todo el repo + import smoke (`vc.config`, `vc.runtime`, `vc.claudecli`, `lk.agent`, `vcctl`).
- `python -m unittest tests.test_pure` (11 tests) verde.
- `grep` refs muertas = 0 (`_ensure_agent_dispatched`, `_dispatch_subsystem_ready`, `create_dispatch`,
  `list_dispatch`, `LIVEKIT_AGENT_NAME`).
- **Smoke headless de arranque (clave anti coin-flip)**: server fresco + worker (load_fnc=0, auto-dispatch) +
  crear room por API (simula el browser) → verificar que `entry()` corre y `LK_CTL_SOCK` responde, SIN ningún
  `create_dispatch`. Repetir 3× cold → debe andar las 3.
- **Validación en vivo del usuario**: `saga-ctl start` (cold) ×3 → Win+Z anda las 3; recargar la pestaña →
  Win+Z sigue andando (valida `close_on_disconnect=False`); `saga-ctl stop` baja todo sin draining-zombie.
- **Lifecycle del socket Win+Z (canon nuestro, debe quedar bien orquestado)**: verificar que `LK_CTL_SOCK`
  se crea en `entry()` al despacharse el agente, SOBREVIVE a la recarga de pestaña (gracias a C4), y se
  limpia en `stop`. El socket sigue siendo glue propio (no primitiva LiveKit) — se conserva por decisión;
  el análisis de migrarlo a RPC/data-channel queda para un ciclo aparte. U8 NO debe degradar su manejo.
- **Eficiencia (verificar el ahorro)**: tras `start`, contar procesos del worker (`pgrep -af lk/agent.py`):
  debe haber ~1 idle process, no 8 (valida `num_idle_processes=1`).

## Riesgos / mitigaciones (del functional-design)
- Auto-dispatch + room zombie → mitigado por server fresco en cada start (C3).
- `close_on_disconnect=False` + sesión colgada si el browser se va para siempre → aceptable mono-usuario;
  `stop` baja todo; el watchdog del orbe vuelve a idle visual.
- `load_fnc=0` enmascara saturación real → irrelevante para 1 worker/1 usuario (sin balanceo).

## Total: 6 steps (Step 0 higiene + 4 de código/docs + 1 resumen). Scope: 3 archivos de código + docs.
