# Build & Test — U1 (Red de tests + CI)

**Ciclo**: 9 · **Rama**: `feature/security-testing-workflow` · **Fecha**: 2026-07-13

---

## Build

| Ítem | Comando | Resultado |
|---|---|---|
| Instalación editable + deps de test | `uv pip install -e ".[test]"` | ✅ OK |
| Sintaxis de todo el repo | `python -m py_compile $(git ls-files '*.py')` | ✅ OK |

**Entorno**: Python 3.12.13, venv gestionado con `uv`. Deps de test: pytest 9.1.1, hypothesis 6.156.6, ruff 0.15.21, mypy 2.3.0, pip-audit 2.10.1.

---

## Test — resultados (estático, corrido por el AI)

| Suite | Comando | Resultado |
|---|---|---|
| **Unit + Property (default)** | `pytest tests/` | ✅ **33 passed, 3 xfailed** |
| **Property — thorough (seguridad, 1000 ej)** | `HYPOTHESIS_PROFILE=thorough pytest tests/test_properties.py` | ✅ **9 passed, 1 xfailed** |
| **Tests viejos intactos** | `pytest tests/test_pure.py` | ✅ **11 passed** |
| **Lint** | `ruff check .` | ✅ All checks passed |
| **Typecheck (3 módulos seguridad)** | `mypy` | ✅ Success, no issues |
| **CVEs (vía CI)** | `pip-audit -r requirements.txt` | ✅ No known vulnerabilities |
| **CVEs (venv completo)** | `pip-audit` | ✅ No known vulnerabilities |

### Los 3 xfailed son intencionales (agujeros a cerrar en U2/U3)
Todos `strict=True`: cuando el agujero se cierre, el test hace **XPASS** y **obliga** a des-marcarlo (la red no deja que el cierre pase inadvertido).

| Test | Documenta | Lo cierra |
|---|---|---|
| `test_p7_blocks_catastrophic` | Bypasses del guard (`rm -r -f`, `rm --recursive --force`) | **U3** (FR2.2/FR2.4) |
| `test_no_auth_by_default_is_the_hole` | `orb_server` sin auth por default (S5) | **U2** (FR3.1) |
| `test_no_god_mode_by_default` | `--dangerously-skip-permissions` por default (S1) | **U3** (FR2.1) |

---

## Tests de integración / performance
**N/A**. U1 es infraestructura de tests, no un servicio con interacciones entre unidades. No hay integración que probar ni carga que medir. (La integración cliente↔servidor aparece en U2; el gate de performance/latencia, en U3.)

---

## Security tests
- **Property-based adversarial**: P4 (framing del socket, anti-inyección), P7 (búsqueda de bypasses del guard), P8 (falsos positivos). Corridos en perfil thorough (1000 ej).
- **Supply chain**: `pip-audit` en verde tras cerrar los CVEs por upgrade (aiohttp/pillow/nltk). Allowlist vacía.
- **Hallazgos de seguridad resueltos en U1**: F1 (crash de arranque del parser), F2 (tipo), F4 (CVEs). Detalle en `construction/U1-tests-ci/code/generation-summary.md`.

---

## NFR1 — Baseline de latencia (para el gate G1 de U3)

**Referencia histórica** (de `saga.log`, 193 mediciones de TTFT, MEZCLADAS con/sin plugins):
- Global: min 0.32s · p50 3.01s · p90 11.47s · max 45.29s (la cola alta = turnos con stack de plugins).
- **Modo rápido** (`CLAUDE_PLUGINS=0`, TTFT <4s, 120 turnos): **mediana ~2.09s**, min 0.32s.

**→ Baseline de referencia para U3: TTFT ~2s en modo rápido.** Es el número que el cambio de permisos NO puede regresar de forma perceptible (NFR1).

⚠️ **Baseline LIMPIO pendiente de captura controlada**: el histórico está mezclado. Antes de que U3 toque los permisos, conviene capturar una tanda controlada (`CLAUDE_PLUGINS=0`, N turnos) como número A del A/B. Se hace en la misma sesión en vivo del usuario.

---

## ⚠️ VALIDACIÓN EN VIVO — pendiente del usuario (lo único que el AI no puede correr)

El AI corrió todo lo estático. Falta **una sola cosa**, que requiere el hardware de audio: confirmar que el **bump de dependencias** (aiohttp 3.13.5→3.14.1, pillow 12.2→12.3, nltk 3.9.4→3.10) **no rompió el turno de voz**.

**Procedimiento** (levantás saga como siempre):
1. `saga-ctl start` (o tu comando habitual de arranque).
2. Un turno de voz normal: Win+Z (o "hey saga" si tenés el wake), decí algo, esperá la respuesta hablada.
3. Verificar: **saga responde por voz, sin errores nuevos**. El orbe late, el TTS suena.
4. (Opcional, para el baseline) mirar el TTFT del turno en `saga.log` (`grep ttft saga.log | tail`).

**Criterio de aceptación**: el turno de voz anda igual que antes. Riesgo bajo (bumps menores, el core livekit/faster-whisper/numpy quedó intacto, import smoke OK), pero es runtime y hay que verlo en vivo.

---

## Estado general

| | |
|---|---|
| **Build** | ✅ OK |
| **Tests estáticos** | ✅ TODO VERDE (33+3xfail · thorough 9+1xfail · ruff · mypy · pip-audit) |
| **Producción tocada** | Solo lo aprobado: `vc/config.py` (F1+F2) + `requirements.txt` (F4) |
| **Validación en vivo** | ⏳ Pendiente del usuario (turno de voz tras el bump de deps) |
| **¿U1 lista para cerrar?** | Sí, condicionada a la validación en vivo |
