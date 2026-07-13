# Code Generation Summary — U1 (Red de tests + CI)

**Ciclo**: 9 · **Rama**: `feature/security-testing-workflow` · **Fecha**: 2026-07-13

---

## Qué se creó / modificó

| Acción | Archivo | Qué |
|---|---|---|
| CREADO | `tests/generators.py` | Generadores de dominio (PBT-07): estados del orbe, contenido de blacklist, comandos catastróficos/benignos, payloads del socket |
| CREADO | `tests/test_properties.py` | Los 10 property-based tests (P1-P10) con perfiles default/thorough |
| CREADO | `tests/test_orb_server.py` | Tests de ejemplo de la superficie HTTP (routing, auth, path traversal, /token) |
| CREADO | `tests/test_config.py` | Tests de ejemplo de la config (flags, parser, settings) |
| CREADO | `.pip-audit-allowlist.txt` | Allowlist de CVEs conocidos (SECURITY-10) |
| MODIFICADO | `pyproject.toml` | Grupo `[test]` (sin pins) + config de pytest/ruff/mypy |
| MODIFICADO | `.github/workflows/tests.yml` | CI endurecido: ruff + mypy + pytest(PBT) + pip-audit + job deep-fuzz |
| NO TOCADO | `tests/test_pure.py` | Los 11 tests existentes, intactos |
| **NO TOCADO** | **todo `vc/`, `lk/`, `orb/*.py`** | **Verificado con `git diff --name-only`: cero código de producción** ✅ |

## Estado de la verificación

- **pytest**: 32 passed, 4 xfailed (los xfail documentan hallazgos, ver abajo).
- **ruff**: limpio (config ignora patrones deliberados de saga: E402, etc.).
- **thorough** (1000 ej): las propiedades de seguridad (P4, P7, P8) pasan/xfailan estable.
- **diff**: cero archivos de producción tocados.
- **mypy**: 🔴 1 finding (ver abajo).
- **pip-audit**: 🟡 CVEs en transitivas (ver abajo).

---

## HALLAZGOS (el valor real de U1)

> **Resolución (autorizada por el usuario 2026-07-13)**: mandato = "que esta rama deje TODA la base de
> testing y seguridad sólida". Por eso F1, F2 y F4 **se resolvieron ahora** (no se difirieron). F3 (guard)
> queda para U3 según el plan. La restricción "U1 no toca producción" se relajó SOLO para estas 3 correcciones
> de seguridad, con autorización explícita.

### 🔴 F1 — BUG REAL: el parser de la blacklist crashea en el arranque (P5) — ✅ RESUELTO
`vc/config.py` — `_read_plugins_blacklist()` hacía `for s in items` asumiendo lista. Con
`{"disabledPlugins": 42}` (o string, o dict) tiraba **`TypeError`** en el **arranque** → saga sin bootear.
- **Fix aplicado**: `if not isinstance(items, list): return []` (degradación segura, como promete el docstring).
- **Estado**: el xfail-strict de `test_p5` se removió; ahora pasa como test verde normal. Bug cerrado.

### 🔴 F2 — mypy: gap de tipo en `vc/config.py:118` — ✅ RESUELTO
`_ensure_saga_settings()` construye un dict heterogéneo; mypy infería un tipo estrecho del literal.
- **Fix aplicado**: `settings: dict = {...}`. mypy en verde sobre los 3 módulos de seguridad.

### 🟠 F3 — BYPASSES del guard, MEDIDOS (P7 → input directo para U3)
El regex del guard (`vc/guard.py`) solo caza flags **pegadas** (`rm -rf`). Hypothesis encontró **2 clases de
bypass** que hoy NO se bloquean:
1. **Flags separadas**: `rm -r -f /`, `rm -r -f ~/algo`
2. **Forma larga**: `rm --recursive --force /`
(+ variaciones con espaciado/tabs/comillas; todas equivalentes.)
- **Estado**: `test_p7` xfail-strict. **Cierre planificado en U3** (FR2.2/FR2.4). Cuando U3 endurezca el guard,
  el test pasa a verde solo (xfail strict → XPASS obliga a des-marcarlo).

### 🟡 F4 — CVEs en dependencias (pip-audit, SECURITY-10) — ✅ RESUELTO por UPGRADE
`aiohttp` (3), `nltk` (1), `pillow` (5), `pip` (6). Ninguna dep directa de saga; transitivas o el pip del runner.
- **Resolución**: se actualizaron a las versiones parcheadas (aiohttp 3.13.5→**3.14.1**, pillow 12.2→**12.3**,
  nltk 3.9.4→**3.10**, + bumps menores). El resolver mantuvo el core INTACTO (livekit, faster-whisper, numpy
  sin cambio). **Import smoke post-upgrade OK** (aiohttp/PIL/nltk + `livekit.agents` + módulos de saga cargan).
- **Lock**: `requirements.txt` (curado, 44 líneas de deps directas) actualizado en las 6 líneas que cambiaron.
  pillow/nltk/regex son transitivas NO congeladas (el lock no las lista) → un install real las resuelve a la
  última parcheada. `pip-audit` da limpio tanto en el venv completo como por la vía del CI (`-r requirements.txt`).
- **Allowlist**: VACÍA (no se aceptó ningún CVE; todos se cerraron por upgrade).
- ⚠️ **PENDIENTE de validación en vivo**: el bump de transitivas del stack de voz (aiohttp lo usa livekit/deepgram)
  resuelve e importa limpio, pero **el turno de voz e2e no se validó en esta sesión** — se confirma en Build & Test
  con el usuario. Riesgo bajo (minor bumps, core intacto), pero es runtime.

### Limitación honesta del audit en CI (deuda menor declarada)
`pip-audit -r requirements.txt` audita las **44 deps directas** del lock curado, NO el cierre transitivo completo
(254 paquetes instalados). Un CVE en una transitiva profunda podría no aparecer en CI (sí en el audit local del
venv completo). Auditar el cierre completo sin instalar el runtime pesado requeriría un full-lock: flageado como
deuda menor (D7), no bloqueante.

### 🟢 Documentados como xfail: los agujeros que U2/U3 deben cerrar
- `test_no_auth_by_default_is_the_hole` (S5): hoy `orb_server` sin `ORB_TOKEN` deja pasar un POST sin auth. **U2 lo invierte.**
- `test_no_god_mode_by_default` (S1): hoy `build_claude_base_args` incluye `--dangerously-skip-permissions`. **U3 lo invierte.**
- Los dos son xfail-**strict**: cuando el agujero se cierre, el test hace XPASS y **obliga** a actualizarlo → la red no deja que el cierre pase inadvertido.

---

## Trazabilidad (FR → hecho)

FR5.1 (Hypothesis) ✅ · FR5.2 (round-trip P3/P4) ✅ · FR5.3 (invariantes P1/P5/P7/P8/P10) ✅ ·
FR5.4 (idempotencia P2/P6) ✅ · FR5.5 (ejemplos orb_server/config) ✅ · FR5.6 (CI: ruff+mypy+seed) ✅ ·
FR4.1 (pip-audit) ✅.

## Deuda declarada (Q2=A)
Sin tests: `lk/agent.py`, `lk/wakeword.py`, `lk/claude_llm.py`, `claude_daemon.py`, `vcctl.py`,
`vc/claudecli.py`, `vc/runtime.py` (requieren mocks pesados de LiveKit/audio/subprocess; no aportan a la
seguridad). Registrada en `docs/tech-debt-plan.md`.

## Baseline de latencia (NFR1)
Procedimiento: TTFT desde `saga.log` (instrumentación existente del Ciclo 5). **A capturar antes de que U3
toque los permisos** — es el número contra el que se mide el gate G1 de U3.
