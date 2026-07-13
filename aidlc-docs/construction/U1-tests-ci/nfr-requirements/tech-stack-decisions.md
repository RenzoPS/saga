# Tech Stack Decisions — U1 (Red de tests + CI)

> **PBT-09 (regla bloqueante)**: el framework de property-based testing debe estar seleccionado, justificado y declarado como dependencia del proyecto. Este documento lo cumple.

**Contexto verificado**: Python **3.12** (venv 3.12.13, CI 3.12, `.python-version` = 3.12). Hoy `pyproject.toml` **no tiene grupo de dependencias de test**.

---

## D1 — Framework PBT: **Hypothesis** ✅ (PBT-09)

**Decisión**: Hypothesis.

**Rationale**: es el framework PBT de referencia para Python — el propio `property-based-testing.md` del framework AI-DLC lo lista como la opción recomendada para Python ("Mature, excellent shrinking"). No hay alternativa seria en el ecosistema.

**Verificación de los requisitos que PBT-09 exige** (los cuatro):

| Requisito de PBT-09 | ¿Hypothesis lo cumple? |
|---|---|
| Generadores custom para tipos de dominio | Sí — `@composite` + `strategies`. Es lo que usaremos para el generador de comandos shell (E6) |
| Shrinking automático de los casos que fallan | Sí, y es su punto más fuerte. Reduce el contraejemplo a su forma mínima |
| Reproducibilidad por seed | Sí — `derandomize` / seed reportada en el fallo, y `@reproduce_failure` para replay exacto |
| Integración con el test runner del proyecto | Sí — funciona con pytest y con `unittest.TestCase` |

**Cómo entra**: dependencia de test, **sin pin de versión** (se toma la que resuelva el package manager; el proyecto solo pinea donde hay un motivo).

---

## D2 — Test runner: **pytest** (migración desde `unittest`)

**Decisión**: pytest (Q1=B del Functional Design).

**Rationale**:
- El argumento que sostenía `unittest` era "**stdlib-only, el CI no instala dependencias**". Ese argumento **se cae solo** en cuanto entra Hypothesis: ya vamos a instalar deps de test igual.
- Los tests de `orb_server` (levantar el server en un puerto libre, tumbarlo, verificar rechazos de auth y CORS) son sustancialmente más limpios con fixtures que con `setUp`/`tearDown`.
- **Costo de migración: cero.** pytest ejecuta los `unittest.TestCase` existentes **sin modificarlos**. Los 11 tests actuales siguen corriendo tal cual.

**Impacto en CI**: el step `python -m unittest tests.test_pure` pasa a `pytest`, y ahora sí hay que instalar el grupo de test.

---

## D3 — Lint: **ruff** (todo el repo)

**Decisión**: `ruff` sobre todo el repo (Q3=C del Units Generation).

**Rationale**: rápido, sin configuración pesada, y atrapa errores reales (imports muertos, variables sin usar, shadowing). Cierra la deuda **D2** de `docs/tech-debt-plan.md` ("sin lint / typecheck / CI"), que estaba abierta desde el Ciclo 1.

---

## D4 — Typecheck: **mypy**, acotado a los 3 módulos de seguridad

**Decisión**: `mypy` **solo** sobre `vc/guard.py`, `vc/config.py`, `orb/orb_server.py`.

**Rationale**: el codebase **no tiene anotaciones de tipo sistemáticas** (verificado: hay algunas, en formato string). Correr `mypy` sobre todo el repo produciría un muro de ruido, y anotarlo entero es un refactor que **no es de seguridad** y no pertenece a este ciclo. Los tres módulos elegidos son exactamente los que este ciclo toca y donde un error de tipos **sí puede ser un agujero**. Rigor donde importa, sin frenar el ciclo.

---

## D5 — Auditoría de dependencias: **pip-audit**, bloqueante con allowlist

**Decisión**: `pip-audit` en CI. **Falla el build** ante un CVE conocido, con un archivo de allowlist versionado para los aceptados explícitamente (Q2=C del Functional Design).

**Rationale**: SECURITY-10 exige un escáner de vulnerabilidades en el pipeline. Pero saga arrastra árboles de dependencias grandes (livekit, onnxruntime, faster-whisper): un CVE en una **transitiva sin patch disponible** dejaría el CI rojo y trabado, sin nada que se pueda hacer. Y **un CI que está siempre rojo deja de leerse** — que es peor que no tenerlo. La allowlist (con justificación escrita por cada CVE aceptado) es lo que sostiene la regla sin volver el semáforo decorativo.

---

## D6 — Configuración de Hypothesis: perfiles + deadline

**Perfiles** (Q1=B del NFR plan):
- **`default`** (100 ejemplos): propiedades comunes. Corre en CI en cada push.
- **`thorough`** (1000+ ejemplos): propiedades de **seguridad** (P4 framing del socket, P7 bypasses del guard, P8 falsos positivos). Es donde más pagan los ejemplos extra — la búsqueda adversarial necesita volumen. Ejecutable a demanda, sin frenar cada push.

**Deadline** (Q2=B del NFR plan): `deadline=None` en las propiedades con **I/O real** (P5 parser de blacklist, P6 settings); default (200ms) en las puras.

**Rationale del deadline**: PBT-08 dice que los fallos flaky se **investigan, no se suprimen** — y estoy de acuerdo. Pero un timeout por I/O en un runner de CI compartido **no es un fallo real, es ruido**. Apagar el deadline donde hay filesystem elimina el ruido; apagarlo en todos lados tiraría señal legítima.

**Seed logging** (PBT-08, obligatorio): la seed se reporta en cada corrida de CI, de forma que cualquier fallo se pueda reproducir exactamente.

---

## D7 — Declaración de dependencias

**Decisión**: `[project.optional-dependencies]` → grupo `test`. Instalable con `pip install -e ".[test]"`.

**Sin pins de versión** (convención del proyecto: solo se pinea donde hay un motivo concreto; hoy están pineadas `faster-whisper`, `edge-tts`, `sounddevice`, `numpy` por razones históricas):

```toml
[project.optional-dependencies]
test = ["pytest", "hypothesis", "ruff", "mypy", "pip-audit"]
```

**Alternativa descartada**: `[dependency-groups]` (PEP 735). Más moderno, pero requiere pip reciente y no aporta nada concreto acá. La opción más simple que cumple.

---

## Resumen

| Necesidad | Herramienta | Regla que satisface |
|---|---|---|
| Property-based testing | **Hypothesis** | **PBT-09** ✅ |
| Test runner | **pytest** | — |
| Lint | **ruff** | Deuda D2 |
| Typecheck (3 módulos) | **mypy** | Deuda D2 |
| CVEs en dependencias | **pip-audit** (bloqueante + allowlist) | **SECURITY-10** ✅ |
| Shrinking + seed | Hypothesis (nativo) | **PBT-08** ✅ |
