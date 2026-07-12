# Execution Plan — Ciclo 3: Fix buffer de audio + feedback "no hay voz"

**Generado**: 2026-06-23
**Tipo**: Bug Fix + Enhancement — Brownfield
**Alcance**: `lk/agent.py` (flujo de audio del agente LiveKit). Sin componentes nuevos.

---

## Detailed Analysis Summary

### Transformation Scope
- **Archivos a modificar**: `lk/agent.py`
- **Archivos sin tocar**: `lk/wakeword.py`, `vc/`, `orb/`, modelo, configs
- **Sin** dependencias nuevas, infra, ni servicios.

### Change Impact Assessment
- **Fix buffer**: `session.clear_user_turn()` al entrar en rec → descarta el backlog acumulado en
  idle. Afecta tanto wake como Win+Z (ambos abren el mismo mic).
- **Feedback**: `orb_state("error")` (amarillo) cuando no hay voz; reemplaza `cancel` en ese caso.
- **Reactivar wake**: `SAGA_WAKE_ENABLED=1`.

### Risk Assessment
- **Riesgo 1** (MEDIO): el buffer de `rtc.AudioStream` es opaco; `clear_user_turn` recrea el STT
  pero la purga total es empírica. Mitigación: validar en vivo; si persiste, escalar (descartar
  primer chunk al abrir).
- **Riesgo 2** (BAJO): tocar el flujo de audio puede afectar Win+Z. Mitigación: probar los 3 casos
  (wake no-voz, wake con-voz, Win+Z).
- **NFR**: no manipular buffers a mano (restricción dura); no regresar latencia.

---

## Phases to Execute

### INCEPTION PHASE (Ciclo 3)
- [x] Workspace Detection — reutilizado de Ciclo 1
- [x] Reverse Engineering — reutilizado de Ciclo 1 (brownfield vigente)
- [x] Requirements Analysis — COMPLETO (buffer-fix-requirement-questions.md: Q1 clear_user_turn,
      Q2 amarillo SÍ, Q3 reactivar wake SÍ)
- [x] User Stories — SKIP (bugfix acotado, sin ambigüedad de scope)
- [ ] Workflow Planning — **EN CURSO** (este documento)
- [x] Application Design — SKIP (sin componentes/servicios nuevos)
- [x] Units Generation — SKIP (entregable único)

### CONSTRUCTION PHASE (Ciclo 3)
- [x] Functional Design — **SKIP** — lógica acotada (3 cambios en `_press`/handlers); sin modelos
  ni estado nuevo.
- [x] NFR Requirements — **SKIP** (extensiones opt-out).
- [x] NFR Design — **SKIP**.
- [x] Infrastructure Design — **SKIP** (sin infra).
- [ ] Code Generation — **EXECUTE**
- [ ] Build and Test — **EXECUTE**

### OPERATIONS PHASE
- [ ] Operations — el commit/push cuenta como entrega (proyecto local).

---

## Code Generation — Entregables (`lk/agent.py`)

1. **Fix buffer (nativo)**: en `_press()`, al entrar en rec → `session.input.set_audio_enabled(True)`
   seguido de `session.clear_user_turn()` para descartar el backlog acumulado en idle.
2. **Feedback amarillo**: en el handler `user_state_changed -> away` (y/o turno vacío),
   `orb_state("error")` (amarillo "No te entendí") en vez de `cancel`.
3. **Reactivar wake**: `SAGA_WAKE_ENABLED=1` en `.env.local`.
4. **Cleanup**: quitar el log de debug `agent_state -> ...` si ya no hace falta.

---

## Build and Test — Criterios de aceptación
1. `py_compile lk/agent.py` → sin errores.
2. **En vivo**: grabás y NO hablás → orbe amarillo "No te entendí" → idle (no cuelga).
3. **En vivo**: grabás, hablás, esperás → responde → idle limpio.
4. **Log**: `audio_duration` al abrir ya NO muestra el backlog (ej. ~0-2s, no 121s).
5. Win+Z y wake (SAGA_WAKE_ENABLED=1), ambos sin colgar el orbe.
6. Latencia Deepgram+Claude sin regresión.

---

## Success Criteria
- El orbe nunca queda pegado en "Grabando".
- Sin voz → feedback amarillo claro → idle.
- Wake reactivado y usable en vivo.
- Sin tocar buffers/streaming a mano (solo API nativa LiveKit).
