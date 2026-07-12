# Ciclo 8 — Requirements: Limpieza de deuda técnica

**Fecha**: 2026-07-12
**Tipo**: cleanup / refactor (brownfield). Sin lógica ni componentes nuevos.
**Profundidad**: Minimal-Standard (entregable acotado, riesgo bajo, verificable estáticamente).
**Fuente**: `docs/tech-debt-plan.md` + `aidlc-docs/inception/reverse-engineering/code-quality-assessment.md`
(deuda "viva" identificada en el doc-sync 2026-07-12).

## Intent Analysis

Dejar el código impecable removiendo deuda muerta/vestigial que quedó tras las migraciones
U7/U7.1/U7.2/U10, **sin tocar el flujo de voz** ni cambiar comportamiento observable. Es el ítem
"Limpieza de deuda técnica" elegido como próximo ciclo AI-DLC.

## Scope

**IN (core, verificado contra código real, no de memoria):**
- FR1 — Remover la **cadena muerta del cancel SIGUSR2** (flujo clásico) en `vc/runtime.py`.
- FR2 — Remover **dependencias declaradas sin uso** de `pyproject.toml`.

**OUT (fuera de este ciclo):**
- Bug TTS Deepgram en modo agéntico (bug funcional, requiere research dedicado — otro ciclo).
- Ciclo 6 (speaker verification), wake fine-tune, saga headless/LAN.
- Cualquier cambio al flujo de voz (turnos, STT/LLM/TTS, wake, orbe).

**OPCIONAL (a decidir — ver Preguntas abiertas):** wake executor shutdown · pin LiveKit · lint/CI.

## Functional Requirements (verificados)

### FR1 — Cadena muerta del cancel SIGUSR2 (`vc/runtime.py`)
Evidencia (grep de callers, 2026-07-12):
- `cancel_handler` (SIGUSR2): **NO está registrado** como signal handler en ningún módulo
  (`rg SIGUSR2|signal.signal` → 0 registros de `cancel_handler`). Muerto.
- `kill_current_proc`, `cancel_streamer`: solo los llama `cancel_handler`. Muertos por transitividad.
- `set_current_streamer`, `_current_streamer`: **0 callers**. Muertos.
- `set_current_proc` / `_current_proc`: los llama `vc/claudecli.py` (179, 232), **pero el único lector
  de `_current_proc` era `kill_current_proc`**. Al remover la cadena, `set_current_proc` escribe un
  estado que nadie lee → los 2 calls en claudecli quedan **no-op** (claudecli mata su `proc` local y
  usa el flag `_cancel`; no depende de `runtime._current_proc`). Removibles sin cambiar comportamiento.

**Requisito**: eliminar `cancel_handler`, `kill_current_proc`, `cancel_streamer`, `set_current_streamer`,
`set_current_proc` y las globales `_current_streamer` / `_current_proc` de `vc/runtime.py`; y en
`vc/claudecli.py` quitar el import + los 2 calls a `set_current_proc`. Conservar `_cancel` (evento
vivo, lo usa el path de cancel real).

### FR2 — Dependencias muertas (`pyproject.toml`)
Evidencia: `rg turn_detector|noise_cancellation|MultilingualModel|BVC` en `lk/` `vc/` → **solo
comentarios históricos, 0 imports**.
- `livekit-plugins-turn-detector`: reemplazado por VAD puro en U10 (`turn_detection="vad"`). Sin carga.
- `livekit-plugins-noise-cancellation` (BVC): inerte en self-hosted (requiere LiveKit Cloud). Sin import.

**Requisito**: remover ambas líneas de `[project.dependencies]` en `pyproject.toml`.

## Non-Functional / Constraints
- **NFR1 — No regresión funcional**: el flujo de voz (turnos/wake/STT/LLM/TTS/orbe) NO se toca; el
  comportamiento observable no cambia. Verificación estática obligatoria antes de cerrar.
- **NFR2 — Reversibilidad**: cambios chicos, en rama aparte (`feat/ciclo8-cleanup-deuda`), revertibles.
- **NFR3 — No tocar el entorno sin OK**: `pip uninstall` / regenerar `requirements.txt` toca el venv
  del usuario → requiere confirmación explícita (ver Q2).

## Extensiones (Extension Configuration) — OPT-IN A DECIDIR POR EL USUARIO

> Corrección 2026-07-12: en la primera pasada di el opt-out por heredado sin preguntar. El framework
> exige presentar estos opt-in en Requirements. Van acá; los responde el usuario.

### Question: Security Extensions
¿Se aplican las reglas de Security como constraints bloqueantes?
- **A)** Sí — enforce todas las reglas SECURITY (recomendado para apps production-grade).
- **B)** No — saltear (PoCs, prototipos, experimentales).
- **X)** Otro.

[Answer]: **B** (delegado al AI, 2026-07-12). El ciclo BORRA código muerto; no agrega superficie de
red, auth, manejo de secretos ni entrada de usuario. Sin cambios que evaluar contra reglas de seguridad.

### Question: Resiliency Extensions
¿Se aplica el resiliency baseline (best practices de diseño, AWS Well-Architected Reliability)?
- **A)** Sí — aplicar como guía direccional (workloads business-critical).
- **B)** No — saltear (PoCs, prototipos, iteración rápida).
- **X)** Otro.

[Answer]: **B** (delegado al AI, 2026-07-12). App de escritorio single-user local; el ciclo no toca
disponibilidad/DR/observabilidad. N/A para un cleanup.

### Question: Property-Based Testing Extension
¿Se aplican reglas de PBT (Hypothesis)?
- **A)** Sí — enforce PBT como bloqueante (lógica de negocio, transformaciones, serialización).
- **B)** Partial — PBT solo para funciones puras y round-trips de serialización.
- **C)** No — saltear (CRUD simple, UI-only, capas finas sin lógica).
- **X)** Otro.

[Answer]: **C** (delegado al AI, 2026-07-12). El ciclo no introduce funciones puras ni serialización
nuevas (solo REMUEVE código). Los `tests/test_pure` existentes (11/11) cubren lo vigente. PBT queda
como recomendación abierta en docs/tech-debt-plan.md (R2), no como gate de este ciclo.

> Mi lectura (NO decisión): es un cleanup que **borra** código muerto, sin lógica/serialización nueva
> ni superficie de red nueva → las tres tienden a **No** (Security B / Resiliency B / PBT C). Pero es
> tu llamada. Si elegís PBT B/A, el ciclo sumaría tests de propiedad sobre las funciones puras.

## Preguntas abiertas (responder acá o en el chat)

### Q1 — Alcance del ciclo
Además del **CORE (FR1 + FR2)**, ¿qué optativos entran?
- **A)** Solo CORE (FR1 + FR2). *(recomendado: bajo riesgo, no toca el flujo de voz)*
- **B)** CORE + wake executor shutdown (`lk/wakeword.py`, async lifecycle, algo más de riesgo).
- **C)** CORE + lint/CI (ruff + extender CI; agrega dep dev + config, scope aparte).
- **D)** Todo (CORE + wake shutdown + pin LiveKit + lint/CI). Nota: el **pin LiveKit contradice la
  convención explícita del repo** (livekit sin pin + lock en `requirements.txt`).

[Answer]: **A** (delegado al AI, 2026-07-12). Solo CORE. Justificación: máximo valor/riesgo. Wake
shutdown y lint/CI quedan como deuda anotada para otro ciclo; pin LiveKit se descarta por contradecir
la convención del repo.

### Q2 — Desinstalación de las deps muertas (FR2) en el venv
- **A)** Solo editar `pyproject.toml`. NO toco el venv ni `requirements.txt`; vos corrés
  `pip uninstall` + refreeze cuando quieras. *(recomendado)*
- **B)** Además hago `pip uninstall` de las 2 + regenero `requirements.txt`, con snapshot previo
  (`pip freeze`) para revertir. Toca tu entorno.

[Answer]: **A** (delegado al AI, 2026-07-12). Solo editar `pyproject.toml`; no toco el venv ni
`requirements.txt`. El `pip uninstall` + refreeze queda anotado como paso manual del usuario.

## Verificación (proporcional, se detalla en Build & Test)
`py_compile` de todo el repo · `tests/test_pure` 11/11 · import smoke (runtime/claudecli/agent/daemon)
· `rg` refs=0 de todo lo borrado · confirmar `_cancel`, `os`/`signal` siguen vivos donde se usan.
