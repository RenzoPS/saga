# NFR Requirements Plan — U1 (Red de tests + CI)

**Unidad**: U1 · **Ciclo**: 9 · **Extensiones bloqueantes**: SECURITY · PBT (full)

> Este stage es **obligatorio por PBT-09** (regla bloqueante): la selección del framework de property-based testing debe quedar documentada como decisión de tech stack.

---

## A. Contexto verificado (no supuesto)

| Dato | Valor real | Fuente |
|---|---|---|
| Python del proyecto | **3.12** | `.python-version` = 3.12 · venv = 3.12.13 |
| Python del CI | **3.12** | `.github/workflows/tests.yml` (`setup-python`) |
| Deps de test hoy | **Ninguna** | `pyproject.toml` no tiene grupo de test |
| Suite hoy | `unittest` stdlib-only, sin instalar deps en CI | `tests.yml` |

---

## B. Preguntas (respondidas por delegación del usuario — "lo dejo a tu criterio")

### Question 1: ¿Cuántos ejemplos genera Hypothesis? (profundidad vs tiempo de CI)
El default de Hypothesis es 100 ejemplos por propiedad. Para las propiedades de seguridad (P7: buscar bypasses del guard) 100 puede quedarse corto; para las triviales, es de sobra.

A) **Default (100) para todo.** Simple, CI rápido. Riesgo: la búsqueda adversarial de bypasses queda superficial.

B) **Perfiles diferenciados**: default (100) en CI para las propiedades comunes, y un **perfil `thorough`** (1000+ ejemplos) para las de seguridad (P4, P7, P8), ejecutable a demanda y/o en un job aparte que no bloquee el push.

C) **Alto (1000) para todo.** Máxima búsqueda, CI lento en cada push.

X) Otro

[Answer]: B — *decidido por delegación.* Rationale: la búsqueda de bypasses (P7) es precisamente donde más ejemplos pagan, y las propiedades triviales (P2 idempotencia) no ganan nada con 1000 corridas. Un CI que tarda deja de correrse.

---

### Question 2: ¿Qué hacemos con el `deadline` de Hypothesis?
Hypothesis falla un ejemplo si tarda más de 200ms (default). Las propiedades que tocan el filesystem (P5 parser de blacklist, P6 settings) hacen I/O real y en un runner de CI compartido pueden pasarse — dando **fallos flaky que no son bugs**.

A) **Dejar el default (200ms) en todo.** Riesgo real de flaky en CI.

B) **`deadline=None` en las propiedades con I/O** (P5, P6), default en las puras. Elimina el flaky sin perder la señal en las que sí son puras.

C) **`deadline=None` global.** Simple pero pierde la detección de regresiones de performance.

X) Otro

[Answer]: B — *decidido por delegación.* Rationale: PBT-08 dice explícitamente que los fallos flaky se investigan, no se suprimen — pero un timeout por I/O en un runner compartido **no es un fallo real**, es ruido. Apagarlo donde hay I/O es la lectura correcta; apagarlo en todos lados sería tirar señal.

---

### Question 3: ¿Dónde se declaran las dependencias de test?
Hoy `pyproject.toml` solo tiene `dependencies` (runtime). El CI corre sin instalar nada.

A) **`[project.optional-dependencies]` → grupo `test`.** Instalable con `pip install -e ".[test]"`. Compatible con todo el tooling actual.

B) **`[dependency-groups]` (PEP 735).** Más moderno, pero requiere pip reciente y todavía no está universalmente soportado.

X) Otro

[Answer]: A — *decidido por delegación.* Rationale: cumple, no agrega riesgo de compatibilidad, y no hay ninguna ventaja concreta de PEP 735 para este caso. La opción más simple que cumple.

---

## C. Plan de generación

- [x] `construction/U1-tests-ci/nfr-requirements/nfr-requirements.md` — Performance (NFR1: método de medición del baseline) · Security (SECURITY-10 + el aporte real de U1) · Maintainability · Reliability · N/A declarados · 7 criterios de aceptación
- [x] `construction/U1-tests-ci/nfr-requirements/tech-stack-decisions.md` — **PBT-09 CUMPLIDO**: Hypothesis (con los 4 requisitos verificados uno por uno) + pytest + ruff + mypy acotado + pip-audit + perfiles/deadline + declaración de deps
- [x] Actualizar `aidlc-state.md` y `audit.md`
