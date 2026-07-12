# Ciclo 8 — Workflow Planning (execution plan)

**Fecha**: 2026-07-12
**Ciclo**: 8 — Limpieza de deuda técnica (cleanup brownfield)
**Requirements**: `inception/requirements/ciclo8-cleanup-requirements.md` (Q1=A CORE, Q2=A solo pyproject)

## Decisión de alcance (Q1=A / Q2=A)
Solo **CORE**: FR1 (cadena muerta cancel SIGUSR2) + FR2 (deps muertas). Optativos (wake shutdown,
pin LiveKit, lint/CI) → **fuera de este ciclo**, anotados como deuda. Deps: solo se edita
`pyproject.toml`; el `pip uninstall` + refreeze queda como paso manual del usuario.

## Stages a ejecutar / saltar

| Fase | Stage | Decisión | Motivo |
|---|---|---|---|
| INCEPTION | Workspace Detection | HECHO | RESUME (brownfield) |
| INCEPTION | Reverse Engineering | SKIP | refresh 2026-07-12 vigente |
| INCEPTION | Requirements Analysis | HECHO | ciclo8-cleanup-requirements.md (aprobado) |
| INCEPTION | User Stories | SKIP | cleanup interno, cero impacto al usuario / sin funcionalidad nueva |
| INCEPTION | Workflow Planning | ESTE DOC | — |
| INCEPTION | Application Design | SKIP | sin componentes/servicios nuevos |
| INCEPTION | Units Generation | SKIP | entregable único (1 unidad de cleanup), sin descomposición |
| CONSTRUCTION | Functional Design | SKIP | sin lógica/modelos nuevos |
| CONSTRUCTION | NFR Requirements | SKIP | extensiones opt-out |
| CONSTRUCTION | NFR Design | SKIP | idem |
| CONSTRUCTION | Infrastructure Design | SKIP | sin infra |
| CONSTRUCTION | Code Generation | EXECUTE | Part 1 (plan) + Part 2 (código) |
| CONSTRUCTION | Build & Test | EXECUTE | verificación estática (no-regresión) |
| OPERATIONS | Operations | N/A | placeholder |

## Unidad de trabajo (única)
**U-cleanup**: remover deuda muerta sin tocar el flujo de voz. Archivos: `vc/runtime.py`,
`vc/claudecli.py`, `pyproject.toml`. Riesgo: **Bajo** (verificado 0 callers vivos + de-indentación
behavior-preserving). Reversible (rama `feat/ciclo8-cleanup-deuda`).

## Secuencia de ejecución
```
Code Gen Part 1 (plan con checkboxes)
   -> Code Gen Part 2 (edición de los 3 archivos)
      -> Build & Test (py_compile + tests + import smoke + grep refs=0)
         -> reporte + gate de commit (commit/push solo con OK del usuario)
```

## Criterio de salida (Definition of Done)
- Los símbolos muertos ya no existen en el repo (`rg` = 0 refs).
- `_cancel`, `log`, `_rotate_log` intactos y vivos.
- `py_compile` OK · `tests/test_pure` 11/11 · import smoke OK.
- Comportamiento del flujo de voz sin cambios (no se tocó agent/wake/STT/LLM/TTS/orbe).
