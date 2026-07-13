# Code Generation Plan — U1 (Red de tests + CI)

> **Este plan es la ÚNICA fuente de verdad de la generación de código de U1.** Part 2 ejecuta exactamente estos pasos, en este orden, y marca cada checkbox al completarlo.

**Unidad**: U1 · **Ciclo**: 9 · **Rama**: `feature/security-testing-workflow`
**Riesgo**: BAJO — **U1 no toca una sola línea de código de producción.**

---

## Contexto de la unidad

- **Trazabilidad**: FR4.1, FR4.2, FR5.1–FR5.6 (ver `inception/application-design/unit-of-work-ciclo9.md`). Este ciclo no tiene user stories (SKIP justificado); los FR cumplen ese rol.
- **Dependencias**: ninguna. U1 es la primera unidad y no depende de nada.
- **Contrato con las otras unidades**: U1 **entrega la red de tests y el baseline de latencia** que U2 y U3 necesitan para verificarse.
- **Propiedades a implementar**: P1–P10 (`U1-tests-ci/functional-design/business-rules.md`).
- **Stack**: Hypothesis + pytest + ruff + mypy + pip-audit (`U1-tests-ci/nfr-requirements/tech-stack-decisions.md`).

### ⚠️ Restricción dura de la unidad (verificable objetivamente)
El diff de U1 **NO debe modificar** nada bajo `vc/`, `lk/`, `orb/*.py`, `vcctl.py`, `claude_daemon.py`, `saga.py`.
**Archivos permitidos**: `tests/**`, `.github/workflows/**`, `pyproject.toml`, y config nueva en la raíz.
Esta restricción se **verifica con `git diff --name-only`** en el paso final. Es lo que hace de U1 una unidad de riesgo bajo.

---

## Pasos

### Paso 1 — `pyproject.toml`: dependencias y configuración de las herramientas
- [x] **1.1** Agregar `[project.optional-dependencies]` con el grupo `test` = `pytest`, `hypothesis`, `ruff`, `mypy`, `pip-audit`. **SIN pins de versión** (convención del proyecto: solo se pinea donde hay motivo concreto).
- [x] **1.2** Configurar `[tool.pytest.ini_options]`: `testpaths = ["tests"]`.
- [x] **1.3** Configurar `[tool.ruff]`: target Python 3.12, excluir `.venv/`, `models/`, `orb/vendor/`. Reglas: el set por defecto (E, F) + imports muertos. **Sin ser dogmático** — el objetivo es atrapar bugs, no imponer estilo sobre un codebase que ya tiene su voz.
- [x] **1.4** Configurar `[tool.mypy]`: **solo** los 3 módulos de seguridad (`vc/guard.py`, `vc/config.py`, `orb/orb_server.py`). No estricto (el codebase no tiene anotaciones sistemáticas): el objetivo es detectar errores de tipo reales, no forzar un refactor de anotaciones.
- [x] **1.5 Verificar**: `pip install -e ".[test]"` en el venv del proyecto (`.venv/`, **no global**) instala todo sin conflictos.

### Paso 2 — `tests/generators.py` (NUEVO): generadores de dominio (PBT-07)
- [x] **2.1** `orb_states()` — estados válidos + válidos con ruido (mayúsculas/espacios) + inválidos plausibles + texto arbitrario + `None` + vacío (entidad E1).
- [x] **2.2** `blacklist_files()` — JSON válido · `disabledPlugins` con tipos equivocados · sin la clave · raíz no-dict · JSON roto · binario · vacío (entidad E3).
- [x] **2.3** `catastrophic_commands()` — generador **compositivo** sobre las plantillas catastróficas, variando: **flags juntas vs separadas** (`-rf` / `-r -f` / `-f -r`) ← *el eje que expone el bypass conocido* · espaciado · quoting · rutas · prefijo `sudo` · separadores · formas largas (`--recursive --force`) (entidad E6).
- [x] **2.4** `benign_commands()` — lectura, inspección, build, instalación de paquetes, git no destructivo, borrado de un archivo puntual (entidad E6).
- [x] **2.5** `socket_payloads()` — bytes arbitrarios · UTF-8 multibyte · **texto con `\n` embebidos** (el caso que motiva P4) · vacío · payloads largos (entidad E5).
- [x] **2.6 Verificar**: los generadores producen datos plausibles (muestreo manual). **PBT-07 prohíbe** primitivos crudos para tipos de dominio — `st.text()` nunca produciría un comando shell realista.

### Paso 3 — `tests/test_properties.py` (NUEVO): las 10 propiedades (PBT-02/03/04/06)
- [x] **3.1 P1 + P2** — `normalize_state`: resultado siempre en `VALID_STATES`, nunca lanza; idempotencia.
- [x] **3.2 P3** — round-trip base64 del socket de control (PBT-02).
- [x] **3.3 P4** ⚠️ **PROPIEDAD DE SEGURIDAD** — el payload base64 **nunca contiene `\n`**. Es la que protege el framing por `readline()` del socket de control contra inyección de comandos.
- [x] **3.4 P5** — el parser de la blacklist **nunca lanza** y siempre devuelve `list[str]` (corre en el arranque: si lanza, saga no levanta).
- [x] **3.5 P6** — `_ensure_saga_settings` es idempotente (PBT-04).
- [x] **3.6 P7** ⚠️ — el guard bloquea lo catastrófico. **SE ESPERA QUE ENCUENTRE BYPASSES** (Q3=A). Se implementa de forma que **los bypasses encontrados se REPORTEN de manera legible** (no un assert opaco), y el test queda marcado como *expected failure* documentado. **NO se arregla el guard acá** — es territorio de U3.
- [x] **3.7 P8** — el guard **NO** bloquea lo legítimo (sin falsos positivos). Un guard que traba trabajo real se termina desactivando.
- [x] **3.8 P9** — `attach`: stateful PBT contra un modelo de referencia (`Optional[str]`), con secuencias aleatorias de `stage`/`clear`/`take`. Incluye **consume-once** (PBT-06).
- [x] **3.9 P10** — keywords de sesión: nunca lanzan; respetan límites de palabra.
- [x] **3.10** Configurar los **perfiles de Hypothesis**: `default` (100 ejemplos) y `thorough` (1000+, para P4/P7/P8). `deadline=None` **solo** en las propiedades con I/O (P5, P6).

### Paso 4 — `tests/test_orb_server.py` (NUEVO): tests de ejemplo de la superficie HTTP
- [x] **4.1** Fixture: levantar `orb_server` en un puerto libre y tumbarlo limpio.
- [x] **4.2** Routing: `/healthz` responde OK; ruta desconocida → 404.
- [x] **4.3** **Auth**: con `ORB_TOKEN` seteado, un POST **sin token** → **403**; con token válido → pasa. *(Documenta el estado ACTUAL; U2 lo endurece para que el token no pueda estar vacío.)*
- [x] **4.4** **El agujero de hoy, escrito como test**: con `ORB_TOKEN` **vacío** (el default de hoy), un POST **sin token** → **pasa**. Este test **documenta el hallazgo S5** y va a tener que **cambiar en U2** — es la prueba viva de que hoy no hay auth.
- [x] **4.5** `_serve_vendor`: path traversal (`/vendor/../../etc/passwd`) → 404 (verifica la defensa que YA existe).
- [x] **4.6** `/token`: sin `LIVEKIT_API_KEY` → 500 con mensaje claro (sin filtrar secretos).

### Paso 5 — `tests/test_config.py` (NUEVO): tests de ejemplo de la config
- [x] **5.1** `build_claude_base_args()`: **hoy** incluye `--dangerously-skip-permissions` por default. *(Documenta el estado ACTUAL — el hallazgo S1. **Este test va a cambiar en U3**, y ese cambio es precisamente la prueba de que el god-mode se fue.)*
- [x] **5.2** `CLAUDE_FAST_FLAGS` según `CLAUDE_PLUGINS`: `off` → `--setting-sources ''`; `on` → sin strip.
- [x] **5.3** `_ensure_saga_settings()`: escribe un `.saga-settings.json` bien formado con el hook del guard; agrega `enabledPlugins` solo si la blacklist no está vacía.
- [x] **5.4** `_read_plugins_blacklist()`: casos concretos (JSON válido, roto, ausente, `_comment` ignorado).

### Paso 6 — `.github/workflows/tests.yml` (MODIFICAR): pipeline endurecido
- [x] **6.1** Instalar el grupo de test (`pip install -e ".[test]"`). **Ojo**: el CI hoy no instala nada; hay que verificar que las deps de test se instalen **sin arrastrar** el stack pesado de runtime (livekit, onnxruntime). Si `-e ".[test]"` arrastra las deps de runtime, instalar solo las de test explícitamente.
- [x] **6.2** Conservar el step `py_compile` (sintaxis de todo el repo).
- [x] **6.3** Agregar `ruff` (todo el repo).
- [x] **6.4** Agregar `mypy` (solo los 3 módulos de seguridad).
- [x] **6.5** Reemplazar `python -m unittest tests.test_pure` por `pytest` (corre los 11 existentes **sin tocarlos** + los nuevos + los PBT), con la **seed de Hypothesis logueada** (PBT-08).
- [x] **6.6** Agregar `pip-audit` — **bloqueante, con allowlist** (SECURITY-10).
- [x] **6.7** Job opcional/manual con el perfil `thorough` de Hypothesis (búsqueda profunda de bypasses), que **no bloquea** cada push.

### Paso 7 — Allowlist de `pip-audit`
- [x] **7.1** Correr `pip-audit` y ver qué sale realmente hoy (no asumir que está limpio).
- [x] **7.2** Si aparecen CVEs sin patch en dependencias transitivas: crear el archivo de allowlist **con la justificación escrita de cada uno**. Si está limpio: crear el archivo vacío con el formato listo.

### Paso 8 — Baseline de latencia (NFR1)
- [x] **8.1** Documentar el procedimiento de medición del TTFT desde `saga.log` (instrumentación **ya existente**, Ciclo 5 — **no se agrega código**).
- [x] **8.2** Capturar el **baseline actual** (`CLAUDE_PLUGINS=0`, antes de tocar los permisos) y registrarlo. **Sin este número, el gate G1 de U3 es una opinión, no una medición.**

### Paso 9 — Verificación estática (Build & Test preliminar de la unidad)
- [x] **9.1** `pytest` en verde localmente (con P7 como expected-failure documentado, si encuentra bypasses).
- [x] **9.2** `ruff` limpio.
- [x] **9.3** `mypy` limpio en los 3 módulos (F2 resuelto).
- [x] **9.4** Los 11 tests existentes **siguen pasando** (verificación de no-regresión de la suite).
- [x] **9.5** ⚠️ **Verificar la restricción dura**: `git diff --name-only` **no muestra** ningún archivo de `vc/`, `lk/`, `orb/*.py`. Si aparece uno, U1 está mal.

### Paso 10 — Documentación
- [x] **10.1** `construction/U1-tests-ci/code/generation-summary.md` — qué se creó/modificó, y **la lista de bypasses del guard que P7 encontró** (input directo para U3).
- [x] **10.2** Actualizar `docs/tech-debt-plan.md`: cerrar la deuda **D2** (sin lint/typecheck/CI) y **R2** (adoptar PBT); declarar la deuda nueva de cobertura (`lk/*`, daemon, vcctl).
- [x] **10.3** Marcar todos los checkboxes de este plan + actualizar `aidlc-state.md` y `audit.md`.

---

## Resumen del alcance

| Acción | Archivos |
|---|---|
| **CREAR** | `tests/generators.py` · `tests/test_properties.py` · `tests/test_orb_server.py` · `tests/test_config.py` · allowlist de pip-audit |
| **MODIFICAR** | `pyproject.toml` · `.github/workflows/tests.yml` · `docs/tech-debt-plan.md` |
| **NO TOCAR** | `tests/test_pure.py` (los 11 existentes siguen igual) · **todo el código de producción** |

**Total**: 10 pasos, ~35 sub-pasos. Riesgo bajo: cero código de producción.

## Nota sobre instalación de dependencias
El Paso 1.5 instala en el **venv del proyecto** (`.venv/`), **no global**. Deps nuevas: `pytest`, `hypothesis`, `ruff`, `mypy`, `pip-audit` (todas de desarrollo, ninguna entra al runtime de saga).
