# Functional Design Plan — U1 (Red de tests + CI)

**Unidad**: U1 — `construction/U1-tests-ci/`
**Ciclo**: 9 (Security + Testing)
**Extensiones bloqueantes**: SECURITY · PBT (full)

> **Nota sobre este stage**: U1 no tiene lógica de negocio (es infraestructura de tests). El Functional Design existe acá **por PBT-01**, que es una regla bloqueante: exige identificar y documentar las *Testable Properties* de cada componente antes de generar código. El "dominio" de esta unidad son las **funciones puras existentes** de saga y sus invariantes.

---

## A. Propiedades identificadas (PBT-01) — leídas del código, no supuestas

| # | Componente | Propiedad | Categoría PBT | Regla |
|---|---|---|---|---|
| P1 | `orb_server.normalize_state` | Para **cualquier** entrada (`str` arbitrario o `None`), el resultado **siempre** pertenece a `VALID_STATES` (10 estados). Nunca lanza excepción. | Invariante (range constraint) | PBT-03 |
| P2 | `orb_server.normalize_state` | `normalize_state(normalize_state(x)) == normalize_state(x)` | Idempotencia | PBT-04 |
| P3 | Socket de control (`orb_server._forward_ctl` → parser del agente) | `b64decode(b64encode(x)) == x` para bytes arbitrarios | Round-trip | PBT-02 |
| P4 | Socket de control — **propiedad de framing (crítica)** | El payload base64 **nunca contiene `\n`**, para ningún input. El protocolo usa `readline()` como framing: si el payload pudiera contener un salto de línea, un adjunto malicioso partiría el mensaje e inyectaría un comando en el socket. | Invariante (de seguridad) | PBT-03 |
| P5 | `config._read_plugins_blacklist` | Para **cualquier** contenido de archivo (JSON válido, JSON roto, binario, vacío), devuelve **siempre** una `list[str]` y **nunca** propaga una excepción (degrada a `[]`). | Invariante (robustez) | PBT-03 |
| P6 | `config._ensure_saga_settings` | Aplicarlo dos veces produce el mismo settings que aplicarlo una vez. | Idempotencia | PBT-04 |
| P7 | `guard.denied` — **cobertura** | Para comandos generados a partir de las **plantillas catastróficas conocidas** (con variaciones de espaciado, orden de flags, comillas, rutas), `denied()` devuelve una etiqueta (no `None`). **Ver §B/Q3: se espera que esta propiedad ENCUENTRE bypasses.** | Invariante (de seguridad) | PBT-03 |
| P8 | `guard.denied` — **ausencia de falsos positivos** | Para comandos benignos generados (`ls`, `cat`, `git status`, `npm install`, `mkdir`, `rm archivo.txt`), `denied()` devuelve `None`. Un guard que bloquea trabajo legítimo se termina desactivando. | Invariante | PBT-03 |
| P9 | `attach` (stage/clear/take) | Máquina de estados con un modelo de referencia simplificado: tras cualquier secuencia de `stage_text`/`clear_text`/`take_staged`, el estado observable coincide con el modelo. Incluye **consume-once**: dos `take_staged()` seguidos nunca devuelven el mismo texto dos veces. | Stateful | PBT-06 |
| P10 | `session.is_reset_command` / `is_visual_command` | Nunca lanzan excepción para ningún string (incluye Unicode, vacío, control chars). Respetan límites de palabra (`is_visual_command("admira")` es `False`). | Invariante | PBT-03 |

**PBT-05 (Oracle)**: **N/A** — no existe implementación de referencia ni versión brute-force contra la cual comparar. Ningún componente de U1 es una optimización de un algoritmo conocido.

**PBT-07 (Calidad de generadores)**: los generadores serán de dominio, no primitivos crudos:
- Generador de **comandos shell** (para P7/P8): compone binario + flags + rutas + separadores + quoting, en vez de `st.text()` random (que nunca produciría un comando shell plausible).
- Generador de **estados del orbe** (P1/P2): mezcla estados válidos, inválidos, con espacios, mayúsculas, y `None`.
- Generador de **contenido de blacklist** (P5): mezcla JSON bien formado, JSON con tipos equivocados, JSON roto, binario.

**PBT-10 (Complementariedad)**: los PBT **no reemplazan** a los tests de ejemplo. Los 11 tests actuales se conservan y se amplían: los ejemplos fijan el comportamiento concreto conocido; las propiedades buscan lo desconocido.

---

## B. Preguntas abiertas

### Question 1: ¿pytest o seguir con `unittest`?
Hypothesis funciona con ambos. Hoy el repo usa `unittest` (stdlib) y el CI corre `python -m unittest tests.test_pure` **sin instalar dependencias** (a propósito: la suite es stdlib-only).

A) **Seguir con `unittest`**. Hypothesis se integra sin problema (`@given` sobre métodos de `TestCase`). Cero cambio de runner. Mantiene la filosofía del repo. Pero: los tests de `orb_server` van a necesitar fixtures (levantar el server en un puerto libre), y en `unittest` eso es más verboso.

B) **Migrar a `pytest`**. Fixtures más limpias, mejor output de fallos, es el estándar de facto y donde Hypothesis está mejor integrado. Costo: una dep más, hay que reescribir el CI y (opcionalmente) los 11 tests actuales.

X) Otro (describir después del tag [Answer]:)

[Answer]: B

**Mi recomendación**: **B (pytest)**. Ya vamos a agregar Hypothesis como dependencia de test igual, así que el argumento "stdlib-only" se cae solo en cuanto entre PBT. Y los tests de `orb_server` (auth, CORS, rechazos) son mucho más limpios con fixtures. `pytest` corre los tests de `unittest` existentes **sin tocarlos**, así que la migración no rompe nada.

---

### Question 2: ¿`pip-audit` bloquea el CI o solo avisa?
Un CVE puede aparecer en una dependencia **transitiva** que vos no controlás (livekit, onnxruntime, faster-whisper arrastran árboles grandes).

A) **Bloqueante**: si hay un CVE conocido, el CI falla (rojo). Máxima presión para actualizar. Riesgo: un CVE en una transitiva sin patch disponible te deja el CI rojo y bloqueado sin que puedas hacer nada.

B) **No bloqueante (warning)**: el CI reporta pero pasa. Cero fricción, pero es fácil de ignorar y termina siendo decorativo.

C) **Bloqueante con allowlist**: falla por default, pero se pueden marcar CVEs específicos como "conocido y aceptado" (con su justificación en un archivo). Es más trabajo de mantenimiento, pero es lo que hace la industria.

X) Otro (describir después del tag [Answer]:)

[Answer]: C

**Mi recomendación**: **C**. Es lo único que sostiene SECURITY-10 sin que el CI se vuelva un semáforo roto que todos ignoran.

---

### Question 3: ¿Qué hago cuando el PBT del guard encuentre bypasses? (esperado, ver P7)
Como te adelanté: el PBT de P7 **casi seguro va a encontrar bypasses en la denylist actual** — `rm -r -f` (flags separados) no matchea el regex `rm\s+-[a-z]*r[a-z]*f`. Eso es el PBT haciendo su trabajo. La pregunta es qué hacemos con el hallazgo **dentro de U1**, dado que el guard es territorio de **U3**.

A) **Registrar y diferir a U3**: el PBT queda marcado como *expected failure* documentado (con la lista de bypasses encontrados), y el endurecimiento del guard se hace en U3, donde ya está planificado (FR2.2). U1 cierra en verde con el hallazgo documentado.

B) **Arreglar en U1**: endurecer la denylist acá mismo, para que el PBT pase en verde. Rompe el límite de la unidad (el guard es U3) pero deja el agujero cerrado antes.

C) **Ajustar la propiedad a la realidad**: que el PBT solo verifique los patrones que la denylist *dice* cubrir, sin buscar bypasses. El test pasa siempre, pero no encuentra nada. (Lo menciono para descartarlo: sería un test decorativo.)

X) Otro (describir después del tag [Answer]:)

[Answer]: A

**Mi recomendación**: **A**. Mantiene los límites de las unidades (que es lo que hace que el orden U1→U2→U3 tenga sentido), y llega a U3 con una **lista concreta y medida de bypasses** que el endurecimiento debe cerrar — en vez de endurecer a ciegas. Es literalmente el flujo que PBT-10 recomienda: el contraejemplo que encuentra el PBT se convierte en un test de regresión permanente.

---

## C. Plan de generación de artefactos (se ejecuta tras responder B)

- [x] `construction/U1-tests-ci/functional-design/business-logic-model.md` — comportamiento de las funciones bajo test, arquitectura de la suite (pytest), pipeline de CI, flujo del hallazgo del guard
- [x] `construction/U1-tests-ci/functional-design/business-rules.md` — **las 10 propiedades (P1-P10)** con categoría PBT, generador y rationale; reglas de decisión (catastrófico vs benigno); PBT-05 marcado N/A
- [x] `construction/U1-tests-ci/functional-design/domain-entities.md` — E1 Estado del orbe · E2 Settings del daemon · E3 Blacklist · E4 Adjunto · E5 Mensaje del socket · E6 Comando shell (entidad de los generadores)
- [x] Registrar las decisiones de Q1/Q2/Q3 — **Q1=B (pytest)** · **Q2=C (pip-audit bloqueante con allowlist)** · **Q3=A (bypasses del guard: registrar y diferir a U3)**
- [x] Actualizar `aidlc-state.md` y `audit.md`

**Frontend components**: N/A (U1 no toca UI).
