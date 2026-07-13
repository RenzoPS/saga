# NFR Requirements — U1 (Red de tests + CI)

**Unidad**: U1 · **Ciclo**: 9 · **Extensiones bloqueantes**: SECURITY · PBT (full)

---

## 1. Performance

### NFR1 (global del ciclo) — Latencia del turno de voz: **NO DETECTABLE**
- **Aplica a U1**: **N/A en cuanto a impacto** — U1 no toca una sola línea de código de producción. Es imposible que degrade la latencia.
- **Pero U1 tiene una responsabilidad clave sobre NFR1**: es donde se **define y construye el método de medición** que U3 va a tener que pasar. Sin baseline medido en U1, el gate de U3 sería una opinión.

**Método de medición (se define acá, se ejecuta en Build & Test)**:
- **Métrica**: TTFT (time-to-first-token) del turno, que ya se loguea en `saga.log` (instrumentación existente del Ciclo 5 — **no se agrega nada nuevo**).
- **Baseline**: turno actual con `CLAUDE_PLUGINS=0` (el modo rápido, ~1.5-2s). Se captura **antes** de tocar los permisos.
- **Criterio**: no es un umbral en milisegundos. Es **perceptual**: el turno no debe *sentirse* más lento. Se valida con (a) comparación A/B del TTFT y (b) el juicio del usuario en vivo ("¿se siente igual?").
- **Si falla**: plan B documentado → `dontAsk` + allowlist (sin clasificador = sin costo por acción).

### NFR-U1.1 — Tiempo de CI
- El CI **no debe volverse tan lento que se deje de correr**. Un pipeline que tarda es un pipeline que se saltea.
- **Criterio**: el perfil `default` de Hypothesis (100 ejemplos) corre en cada push. El perfil `thorough` (1000+, para las propiedades de seguridad) se ejecuta a demanda, **sin bloquear** cada push.

---

## 2. Security

| Requisito | Cómo lo cumple U1 | Regla |
|---|---|---|
| Escaneo de vulnerabilidades en dependencias | `pip-audit` en CI, **bloqueante con allowlist** | **SECURITY-10** |
| Lock file versionado | Ya existe (`requirements.txt` = `pip freeze`) | SECURITY-10 |
| Sin dependencias sin usar | Ciclo 8 ya removió las muertas | SECURITY-10 |
| Deps de fuentes confiables | PyPI oficial; sin fuentes de terceros | SECURITY-10 |
| **Verificación de los controles de seguridad existentes** | **Este es el aporte real de U1 a la seguridad**: P4 (framing del socket), P7/P8 (guard) y P5 (robustez del parser en el arranque) auditan los controles que hoy nadie verifica | SECURITY-11 (defensa en profundidad) |

**Nota honesta sobre el alcance**: U1 **no agrega ni un control de seguridad nuevo**. Lo que hace es **poner bajo prueba los que ya existen** — y en el camino, medir sus agujeros (P7 va a encontrar bypasses del guard). Ese es su valor: U2 y U3 se apoyan en esta red.

---

## 3. Maintainability

| Requisito | Criterio |
|---|---|
| Lint | `ruff` limpio en todo el repo (cierra la deuda D2, abierta desde el Ciclo 1) |
| Typecheck | `mypy` limpio en los 3 módulos de seguridad (`guard`, `config`, `orb_server`) |
| Reproducibilidad de fallos | **PBT-08**: shrinking habilitado + **seed logueada en cada corrida** de CI. Un fallo debe poder replicarse exactamente |
| Generadores no duplicados | **PBT-07**: los generadores de dominio viven en un módulo único (`tests/generators.py`), no copiados por archivo |
| Complementariedad | **PBT-10**: los PBT no reemplazan a los tests de ejemplo. Los 11 existentes se conservan; los contraejemplos que aparezcan se vuelven tests de regresión permanentes |

---

## 4. Reliability

- **Sin flakies tolerados**: PBT-08 exige investigar los fallos flaky, no silenciarlos. Por eso `deadline=None` **solo** en las propiedades con I/O real (donde un timeout en runner compartido es ruido, no un bug) y default en las puras (donde sí es señal).
- **Degradación segura como propiedad**: P5 verifica que el parser de la blacklist **nunca lance** — corre en el arranque de saga; si lanza, saga no levanta.

---

## 5. NFRs marcados N/A (declarados, no omitidos)

| NFR | Estado | Rationale |
|---|---|---|
| **Escalabilidad** | N/A | U1 es infraestructura de tests. No hay carga, ni usuarios concurrentes, ni crecimiento que planificar. |
| **Disponibilidad / DR / failover** | N/A | Extensión de Resiliencia **desactivada** por el usuario (Q3=B del Requirements). saga es una app local monousuario sin SLA. |
| **Usabilidad / accesibilidad** | N/A | U1 no toca UI. |
| **Compliance** | N/A | Sin requisitos regulatorios (uso personal, sin datos de terceros). |

---

## 6. Criterios de aceptación de U1

1. Suite verde en local y en CI (11 tests de ejemplo existentes + los nuevos + los PBT).
2. `ruff` limpio en todo el repo; `mypy` limpio en los 3 módulos de seguridad.
3. `pip-audit` corriendo y bloqueante (con allowlist si hace falta, justificada por escrito).
4. Las 10 propiedades (P1-P10) del Functional Design, implementadas.
5. **Los bypasses del guard que encuentre P7 quedan registrados** (lista concreta) y diferidos a U3 (Q3=A).
6. **El diff no toca código de producción** — verificable objetivamente: nada bajo `vc/`, `lk/`, `orb/*.py`. Solo `tests/`, `.github/`, `pyproject.toml`.
7. Baseline de latencia capturado, para que el gate de U3 tenga contra qué comparar.
