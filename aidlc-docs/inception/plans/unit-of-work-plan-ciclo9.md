# Unit of Work Plan — Ciclo 9 (Security + Testing)

**Stage**: Units Generation — PART 1 (Planning)
**Rama**: `feature/security-testing-workflow`
**Base**: `execution-plan-ciclo9.md` (aprobado) + `ciclo9-security-testing-requirements.md` (aprobado)

---

## A. Estrategia de descomposición (ya decidida en Workflow Planning)

3 unidades **secuenciales**, ordenadas por riesgo creciente. El criterio de agrupación NO es "por archivo" ni "por capa", sino **por superficie de riesgo y por dependencia de verificación**: cada unidad deja el terreno listo para que la siguiente se pueda verificar.

| Unidad                             | Superficie                                          | Riesgo   | Depende de        |
| ---------------------------------- | --------------------------------------------------- | -------- | ----------------- |
| **U1 — Red de tests + CI**         | `tests/`, `.github/workflows/`, `pyproject.toml`    | Bajo     | —                 |
| **U2 — Hardening de `orb_server`** | `orb/orb_server.py`, `orb/orb.html`, `vc/config.py` | Medio    | U1 (red de tests) |
| **U3 — Modelo de permisos**        | `vc/config.py`, `vc/guard.py`                       | **Alto** | U1, U2            |

---

## B. Preguntas abiertas (necesitan tu respuesta)

Estas cuatro afectan esfuerzo real o el flujo de trabajo. No las asumo.

### Question 1: Estrategia de merge

¿Cómo integramos el trabajo a `main`?

A) **Un PR por unidad** (3 PRs): U1 → merge → U2 → merge → U3 → merge. Cada unidad se valida en vivo y entra sola. Más ceremonia, pero si U3 sale mal, U1 y U2 ya están seguros en `main`.

B) **Un solo PR al final** con las 3 unidades. Menos ceremonia, pero el cambio riesgoso (U3) viaja junto con lo seguro: si U3 no pasa el gate de latencia, o se revierte todo o hay que desarmar el PR.

C) **Dos PRs**: uno con U1+U2 (lo seguro) y otro con U3 (el riesgoso, que puede necesitar iteración o terminar en `dontAsk`).

X) Otro (describir después del tag [Answer]:)

[Answer]: A

---

### Question 2: Alcance de los tests example-based en U1

Hay 12 módulos sin un solo test. Cubrirlos todos no cuesta lo mismo.

A) **Solo la superficie de seguridad** (lo que este ciclo toca y necesita red): `orb_server` (routing, auth, CORS, validación), `vc/config.py` (construcción de flags, parser de blacklist, settings), `vc/guard.py` (ampliado). Son testeables sin mocks pesados. El resto queda como deuda declarada.

B) **Superficie de seguridad + los módulos puros que falten** (A + lo que sea testeable sin levantar audio/red/subprocess).

C) **Todo lo que no tiene tests**, incluidos `lk/agent.py`, `lk/wakeword.py`, `claude_daemon.py`, `vcctl.py`. Requiere mocks pesados de LiveKit, de subprocess y de audio; es un ciclo entero en sí mismo y no aporta a la seguridad.

X) Otro (describir después del tag [Answer]:)

[Answer]: A

**Mi recomendación**: A. Es la red que este ciclo necesita, y evita convertir el ciclo de seguridad en un ciclo de cobertura. La deuda restante se declara explícitamente en `docs/tech-debt-plan.md`.

---

### Question 3: Lint y typecheck en CI

Hoy no hay ninguno de los dos. Nota: el codebase **no tiene type hints sistemáticos** (hay algunos, en formato string).

A) **Solo `ruff`** (lint + format check). Rápido, cero fricción, atrapa errores reales (imports muertos, variables sin usar, bugs de shadowing). Typecheck queda como deuda.

B) **`ruff` + `mypy`**. Más riguroso, pero sobre un codebase sin anotaciones sistemáticas `mypy` va a escupir mucho ruido, y adaptarlo es un trabajo aparte (no de seguridad).

C) **`ruff` + `mypy` solo sobre los módulos de seguridad** (`vc/guard.py`, `vc/config.py`, `orb/orb_server.py`), que son los que este ciclo toca y donde un error de tipos sí puede ser un agujero.

X) Otro (describir después del tag [Answer]:)

[Answer]: C

**Mi recomendación**: C. Rigor donde importa, sin frenar el ciclo con un refactor de anotaciones en todo el repo.

---

### Question 4: Alcance del guard extendido a tools MCP (FR2.3)

Hoy el guard solo matchea `Bash`. Con `CLAUDE_PLUGINS=1`, los tools MCP no tienen ningún control. ¿Qué política aplicamos?

A) **Auditar, no bloquear**: el guard loggea toda invocación de tool MCP (para tener visibilidad de qué hace saga), pero no deniega nada. Cero riesgo de romper funcionalidad; cero protección efectiva.

B) **Denylist de tools MCP destructivos**: bloquear los que borran/mandan/publican (ej. `delete_note`, `merge_pull_request`, tools de mail/deploy). Requiere enumerar los tools peligrosos de tus MCPs.

C) **Confiar en el clasificador de `auto`**: en `auto` mode, los tools MCP también pasan por el sistema de permisos nativo. Sumar reglas `permissions.deny` declarativas para los casos catastróficos y no meter lógica propia en el guard para MCP.

X) Otro (describir después del tag [Answer]:)

[Answer]: C, es imposible abarcar todos los casos, los mcps tienen tools obvio, pero hoy yo cuento con X plugings con sus respectivas tools, destructivas o no, pero otros usuarios pueden contar con Y plugings con Z tools entendes? No podemos abarcar todos los casos en la inmensidad de plugings, si el usuario permite un MCP tipo github y le pide a Saga eliminar un repo, saga deberia PROCEDER, en todo caso, hay q asegurarse que la ORDEN llegue de forma EXPLICITA y no IMPLICITA.

**Mi recomendación**: C + B parcial. `auto` ya cubre el caso general; las `permissions.deny` declarativas (que se respetan **incluso en auto**, verificado en la doc) son el lugar correcto para lo catastrófico, y no cuestan latencia porque son reglas, no clasificación. Reservar el guard para Bash, donde ya funciona.

---

## C. Plan de generación (Part 2 — se ejecuta tras aprobar B)

- [x] Generar `aidlc-docs/inception/application-design/unit-of-work-ciclo9.md` — definición de las 3 unidades, responsabilidades, archivos que toca cada una, criterios de aceptación
- [x] Generar `aidlc-docs/inception/application-design/unit-of-work-dependency-ciclo9.md` — matriz de dependencias + orden de ejecución + puntos de coordinación (`orb.html` ↔ `orb_server` = C1; `config.py` fuente única = C2; `config.py` tocado por U2 y U3 = C3)
- [x] Generar el **mapa FR → unidad** (incluido en unit-of-work-ciclo9.md; reemplaza al story-map: este ciclo NO tiene user stories)
- [x] Validar que **todos** los FR estén asignados — **20 FR + 5 NFR asignados, cero huérfanos** ✅
- [x] Validar los límites de las unidades — 3 puntos de coordinación declarados (C1, C2, C3)
- [x] Registrar la política de merge (Q1=A: un PR por unidad) en los artefactos
- [x] Actualizar `aidlc-state.md` y `audit.md`

---

## D. Categorías de decomposición evaluadas (trazabilidad del framework)

| Categoría                    | ¿Aplica? | Resolución                                                                                                                                                                                  |
| ---------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Story Grouping**           | N/A      | El ciclo no tiene user stories (SKIP justificado). La agrupación se hace por FR y por superficie de riesgo.                                                                                 |
| **Dependencies**             | **Sí**   | U1 → U2 → U3, secuencial estricto. Punto de coordinación crítico: `orb.html` ↔ `orb_server` (U2). Se documenta en la matriz.                                                                |
| **Team Alignment**           | N/A      | Un solo dev (Renzo) + AI. Sin límites de ownership ni colaboración multi-equipo.                                                                                                            |
| **Technical Considerations** | **Sí**   | Las unidades tienen perfiles de riesgo MUY distintos (bajo/medio/alto) y distintos métodos de verificación (CI verde vs validación perceptual en vivo). Eso es lo que justifica separarlas. |
| **Business Domain**          | N/A      | Sin bounded contexts: es una app local monousuario.                                                                                                                                         |
| **Code Organization**        | N/A      | Brownfield. La estructura existe y no cambia.                                                                                                                                               |
