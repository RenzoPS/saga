# U8 — Dispatch consistente — Generation Summary

> AI-DLC · CONSTRUCTION · Code Generation (Part 2). Brownfield. Ejecutado 2026-06-24.
> Plan: `../../plans/U8-dispatch-consistente-code-generation-plan.md`. Todo verificado contra
> livekit-agents 1.6.0 instalado (inspect/getsource), no de memoria.

## Archivos modificados (código)
- **`lk/agent.py`** (MOD):
  - C1: `server = AgentServer(load_fnc=lambda: 0.0, drain_timeout=0, num_idle_processes=1)`. Mata el coin-flip
    (worker siempre disponible), stop sin draining-zombie, 8→1 procesos idle (RAM/CPU).
  - C2: `@server.rtc_session()` sin `agent_name` (auto-dispatch) + `os.environ.pop("LIVEKIT_AGENT_NAME", None)`
    defensivo + quitado el import de `LIVEKIT_AGENT_NAME`.
  - C4: `session.start(..., room_input_options=RoomInputOptions(close_on_disconnect=False))` + import de
    `RoomInputOptions`. Socket Win+Z sobrevive a la recarga de pestaña.
- **`vcctl.py`** (MOD):
  - C2: ELIMINADA `_ensure_agent_dispatched()` entera (create_dispatch/list_dispatch/delete + retry 90s) y su
    llamada (paso 4.5). Reemplazada por helper `_kill_pids()` (SIGTERM→SIGKILL por pid exacto, patrón de stop).
  - C3: `_start_room` reescrito — server y worker FRESCOS en cada start (`_kill_pids` baja los viejos), claude/orb
    se reusan (dedup). Orden nuevo: server→claude+orb→worker(registered)→browser→wait-socket. El browser dispara
    el auto-dispatch; el wait del socket de control es el readiness real del agente.
- **`vc/config.py`** (MOD): eliminada la constante `LIVEKIT_AGENT_NAME` + su comentario (sin uso tras C2).
- **`orb/orb_server.py`** (MOD): comentario del `/token` actualizado a auto-dispatch.

## Docs actualizados (markdown)
- `.claude/CLAUDE.md`: arquitectura (worker/token/orquestación) + gotchas room reescritos a auto-dispatch;
  el gotcha de cold-start/list_dispatch/retry-90s marcado OBSOLETO; agregados load_fnc/close_on_disconnect/frescos.
- `docs/architecture.md`, `docs/operations.md`, `docs/code-guide.md`, `docs/internal-api.md`,
  `docs/tech-debt-plan.md`, `README.md`, `lk/README.md`: dispatch explícito → automático; coin-flip RESUELTO
  con causa raíz real (load_threshold); eliminada `LIVEKIT_AGENT_NAME` de tablas; flujo de arranque nuevo.

## Step 0 (higiene)
- `.github/workflows/tests.yml` revertido (reindent + bumps `checkout@v7`/`setup-python@v6` espurios, no U8).

## Verificación estática (CERRADA)
- `py_compile` de TODO el repo (`git ls-files '*.py'`): OK.
- Import smoke (`vcctl`, `vc.config`, `vc.runtime`, `vc.claudecli`): OK.
- `tests.test_pure`: 11/11 verde.
- grep refs muertas en `.py`: 0 código funcional (solo comentarios + el `pop` intencional).
- Análisis de impacto (grep): wake/orbe/turnos/LLM/STT FUERA del diff. `LIVEKIT_AGENT_NAME` + dispatch vivían
  solo en las 3 zonas reescritas. C3 reusa el claude_daemon → contexto LLM intacto.

## Verificación EN VIVO (pendiente del usuario — no runtime-testeable desde acá)
- Smoke headless ×3 cold: server fresco + worker + crear room por API → `entry()` corre y `LK_CTL_SOCK`
  responde SIN create_dispatch; las 3 sin coin-flip.
- `saga-ctl start` (cold) ×3 → Win+Z anda las 3.
- Recargar la pestaña del orbe → Win+Z sigue andando (valida `close_on_disconnect=False`).
- `pgrep -af lk/agent.py` tras start → ~1 idle process, no 8 (valida `num_idle_processes=1`).
- `saga-ctl stop` → baja todo sin draining-zombie en :8081.

## Riesgos residuales (declarados, bajos)
- Timing del socket Win+Z (aparece tras entrar el browser) — cubierto por `_wait_ready(socket)`.
- Primer turno podría pagar el fork si llega antes de calentar el idle process — mínimo (prewarm calienta el cerebro).
