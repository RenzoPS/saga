# Deuda técnica y plan de remediación

Consolidación de la deuda detectada + plan priorizado. **Es un plan, no una ejecución**: no se tocó
código. Detectada durante el análisis del código.

## Resumen de la deuda

| # | Ítem | Dónde | Severidad |
|---|------|-------|-----------|
| D1 | Lógica de turno **duplicada** clásico vs LiveKit | `vc/app.py:_do_turn` y `lk/claude_llm.py` | Media-alta |
| D2 | Sin lint / typecheck / CI | repo | Media |
| D3 | LiveKit **sin pin** en `pyproject.toml` | `pyproject.toml` | Media |
| D4 | `is_goodbye` huérfana (código muerto testeado) | `vc/session.py` + `tests/test_pure.py` | Baja |
| D5 | `import os` duplicado | `vc/app.py` (líneas 4 y 9) | Trivial |
| R1 | Hardening de seguridad puntual (recomendación) | god-mode, sockets, secretos | Media |
| R2 | Adoptar **PBT-partial** (Hypothesis) (recomendación) | funciones puras | Baja-media |

## Plan priorizado

Orden sugerido por relación impacto/esfuerzo/riesgo. Todo es reversible y de bajo riesgo.

### 1. D5 — `import os` duplicado (quick win)
- **Impacto**: cosmético. **Esfuerzo**: minutos. **Riesgo**: nulo.
- **Acción**: borrar la segunda línea `import os` en `vc/app.py`.

### 2. D4 — `is_goodbye` huérfana
- **Impacto**: claridad (qué está activo). **Esfuerzo**: bajo. **Riesgo**: bajo.
- **Acción**: decidir — (a) borrar `is_goodbye` + sus tests si el modo conversacional no vuelve, o
  (b) dejar un comentario marcándola como reservada para uso futuro. Evitar el limbo actual.

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
  - `clean_for_tts(x)` nunca contiene markdown residual (`*`, backticks).
  - `guard.denied` bloquea siempre cualquier variante de los patrones catastróficos.
  - `attach.take_staged` cumple consume-once (segunda llamada → vacío).
  - chunking: la concatenación de los chunks reconstruye el texto original (round-trip).

### 6. R1 — Hardening de seguridad puntual
- **Impacto**: reduce superficie de riesgo (god-mode + voz). **Esfuerzo**: variable. **Riesgo**: medio (cambia comportamiento).
- **Acción** (evaluar, no automático):
  - Revisar/expandir la denylist de `vc/guard.py` contra nuevos comandos catastróficos.
  - Confirmar perms `0o600` en todos los artefactos sensibles (wav, screenshot, log, sockets) — ya está, mantener.
  - Considerar un modo "no god" más usable para sesiones de riesgo (`VOICE_CLAUDE_SAFE=1` ya existe).

### 7. D1 — Duplicación clásico/LiveKit (la más estructural, último)
- **Impacto**: alto a largo plazo (drift: un comando de voz hay que cablearlo en dos lados). **Esfuerzo**: alto. **Riesgo**: medio-alto (toca el flujo en vivo).
- **Acción**: extraer un núcleo común del turno (detección de keywords → visión → prompt → cancelación)
  que ambos modos invoquen, dejando a cada modo solo su transporte de audio. Hacerlo **con red**:
  `git baseline` + verificación en vivo (Win+Z), por ser código no runtime-testeable desde fuera.
- **Nota**: dejar para el final porque es el único con riesgo real de regresión; los demás son seguros.

## Criterio transversal
Cualquier ejecución de este plan debe terminar con verificación proporcional (`py_compile` +
`tests/test_pure.py` + prueba en vivo del Win+Z cuando toque el flujo), y commit solo con
confirmación explícita.
