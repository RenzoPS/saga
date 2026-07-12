# Ciclo 8 — Code Generation Plan (Part 1)

**Fecha**: 2026-07-12 · **Unidad**: U-cleanup · **Rama**: `feat/ciclo8-cleanup-deuda`
**Alcance**: CORE (FR1 + FR2). Solo edita 3 archivos. Behavior-preserving.

## Pasos

### Paso 1 — `vc/runtime.py`: remover la cadena muerta del cancel SIGUSR2 (FR1)
- [x] Eliminar funciones: `set_current_proc`, `kill_current_proc`, `set_current_streamer`,
      `cancel_streamer`, `cancel_handler`.
- [x] Eliminar globales: `_current_proc`, `_proc_lock`, `_current_streamer`, `_streamer_lock`.
- [x] Eliminar imports que quedan sin uso: `os`, `signal`, `subprocess` (solo los usaban esas funcs).
- [x] Conservar: `log`, `_rotate_log`, `_LOG_MAX`, `_cancel` (evento vivo), imports `threading`/`time`,
      `from .config import LOG_FILE`.
- [x] Actualizar el docstring del módulo (sacar "control de procesos / signal handlers / PID-file";
      la maquinaria de PID ya no vive acá desde U7.2). Comentario de `_cancel` = quién lo setea/lee real.

### Paso 2 — `vc/claudecli.py`: sacar los no-op de `set_current_proc` (FR1)
- [x] Línea import: `from .runtime import log, _cancel, set_current_proc` → `from .runtime import log, _cancel`.
- [x] Eliminar la llamada `set_current_proc(proc)` (post-spawn).
- [x] Reescribir el bloque `try: <stream> finally: set_current_proc(None)`: sacar el `try/finally`
      (existía solo para el no-op) y de-indentar el cuerpo. Conservar TAL CUAL el
      `proc.wait/terminate/kill` post-loop y el `if _cancel.is_set(): return` que le sigue.
- **Verificado**: claudecli mata su `proc` local (no vía runtime); `_cancel` lo setea `lk/claude_llm.py`.
  Los `set_current_proc` eran registro para el SIGUSR2 muerto → removerlos no cambia comportamiento.

### Paso 3 — `pyproject.toml`: remover deps muertas (FR2)
- [x] Eliminar `"livekit-plugins-noise-cancellation"` (BVC, inerte self-hosted, 0 imports).
- [x] Eliminar `"livekit-plugins-turn-detector"` (reemplazado por VAD puro en U10, 0 imports).
- [x] NO tocar el venv ni `requirements.txt` (Q2=A). Anotar el `pip uninstall`+refreeze como paso manual.

### Paso 4 — Verificación estática (se detalla en Build & Test)
- [x] `py_compile` de todo el repo.
- [x] `tests/test_pure` 11/11.
- [x] import smoke: `vc.runtime`, `vc.claudecli`, `lk.agent`, `claude_daemon`.
- [x] `rg` refs=0 de: `cancel_handler`, `kill_current_proc`, `set_current_proc`, `set_current_streamer`,
      `cancel_streamer`, `_current_proc`, `_current_streamer`, `turn-detector`, `noise-cancellation`.
- [x] Confirmar `_cancel` sigue vivo (setter en claude_llm, readers en claudecli).
