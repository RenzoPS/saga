# Ciclo 8 — Build & Test (U-cleanup)

**Fecha**: 2026-07-12 · **Rama**: `feat/ciclo8-cleanup-deuda`
**Objetivo**: verificar no-regresión tras remover deuda muerta (FR1 + FR2). Sin cambios de comportamiento.

## Resultados

| Gate | Comando | Resultado |
|---|---|---|
| Compilación | `git ls-files '*.py' \| xargs .venv/bin/python -m py_compile` | ✅ OK (todo el repo) |
| Unit tests | `.venv/bin/python -m unittest tests.test_pure` | ✅ 11/11 |
| Import smoke | `import vc.runtime, vc.claudecli, claude_daemon` | ✅ OK |
| Parse worker | `ast.parse(lk/agent.py)` | ✅ OK |
| Refs muertas | `rg` de los 7 símbolos borrados | ✅ 0 archivos c/u |
| Deps muertas | `rg noise-cancellation\|turn-detector pyproject.toml` | ✅ 0 (limpio) |
| `_cancel` vivo | setter `lk/claude_llm.py:141`, readers `vc/claudecli.py:85/190/230` | ✅ intacto |

Símbolos verificados removidos (0 refs): `cancel_handler`, `kill_current_proc`, `set_current_proc`,
`set_current_streamer`, `cancel_streamer`, `_current_proc`, `_current_streamer`.

## Análisis de no-regresión
- **Cancelación**: `_cancel` tiene setter vivo en `lk/claude_llm.py` (independiente del `cancel_handler`
  removido) → el path de cancel real no se toca.
- **One-shot fallback**: claudecli sigue matando su `proc` local (`proc.wait/terminate/kill`); los
  `set_current_proc` eran registro para el SIGUSR2 muerto → removerlos no cambia comportamiento.
- **Flujo de voz** (agent/wake/STT/LLM/TTS/orbe): NO tocado (fuera del diff).
- **Deps**: `turn-detector`/`noise-cancellation` sin imports → removerlas de `pyproject.toml` no rompe
  nada. El venv conserva los paquetes hasta que el usuario corra el uninstall (paso manual, Q2=A).

## Estado
Build & Test **CERRADO OK** (estático). Validación en vivo del Win+Z = opcional (el diff no toca el
flujo de voz; cero riesgo funcional). Pendiente: commit/push (con OK del usuario).
