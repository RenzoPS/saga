# Ciclo 8 — Code Generation Summary (U-cleanup)

**Fecha**: 2026-07-12 · **Rama**: `feat/ciclo8-cleanup-deuda` · **Alcance**: CORE (FR1 + FR2)

## Archivos tocados (3)

### `vc/runtime.py` (FR1) — rewrite
Removida la cadena muerta del cancel SIGUSR2 del flujo clásico:
- Funciones: `set_current_proc`, `kill_current_proc`, `set_current_streamer`, `cancel_streamer`,
  `cancel_handler`.
- Globales/locks: `_current_proc`, `_proc_lock`, `_current_streamer`, `_streamer_lock`.
- Imports sin uso: `os`, `signal`, `subprocess`.
- **Conservado**: `log`, `_rotate_log`, `_LOG_MAX`, `_cancel` (evento vivo), `threading`/`time`,
  `from .config import LOG_FILE`. Docstring actualizado.

### `vc/claudecli.py` (FR1)
- Import: `from .runtime import log, _cancel, set_current_proc` → `... log, _cancel`.
- Removido `set_current_proc(proc)` (post-spawn) y `set_current_proc(None)` (finally).
- El `try/…/finally: set_current_proc(None)` (existía solo para el no-op) se de-indentó a bloque plano.
  **Se conservó TAL CUAL** el `proc.wait/terminate/kill` post-loop y el `if _cancel.is_set(): return`.
- Behavior-preserving: claudecli ya mataba su `proc` local; la cancelación real la maneja `_cancel`
  (seteado por `lk/claude_llm.py`, leído acá).

### `pyproject.toml` (FR2)
- Removidas `livekit-plugins-noise-cancellation` (BVC inerte self-hosted) y
  `livekit-plugins-turn-detector` (reemplazado por VAD puro en U10). 0 imports en el código.
- **Venv NO tocado** (Q2=A). Paso manual del usuario: `pip uninstall livekit-plugins-noise-cancellation
  livekit-plugins-turn-detector` + regenerar `requirements.txt` (`pip freeze`).

## Verificación estática (Build & Test)
`py_compile` OK · `tests/test_pure` 11/11 · import smoke (runtime/claudecli/daemon/agent) OK ·
`rg` refs=0 de los 7 símbolos borrados · `_cancel` vivo. Detalle en
`construction/build-and-test/ciclo8-build-and-test.md`.

## Fuera de scope (deuda anotada)
Wake executor shutdown (`lk/wakeword.py`), pin LiveKit (contradice convención del repo), lint/CI (ruff).
