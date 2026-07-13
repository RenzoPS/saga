# Ciclo 9 — Auditoría de Testing + Security · Preguntas de Requirements

**Fecha**: 2026-07-13
**Tipo**: Auditoría + hardening (brownfield). Enhancement de calidad, sin features nuevas.
**Estado**: ⛔ GATE — esperando tus respuestas. No avanzo a Workflow Planning sin esto.

---

## Contexto: lo que YA verifiqué en el código (no de memoria)

Escaneé el repo antes de preguntar. Esto es el terreno real, para que decidas con datos:

### Testing — estado actual

| Ítem                               | Estado real                                                                                                                                                                                                    |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Suite                              | `tests/test_pure.py` — **11 tests, 3 clases**: `TestSessionKeywords` (3), `TestGuardDenylist` (2), `TestAttach` (6)                                                                                            |
| Framework                          | `unittest` (stdlib). Sin pytest, sin Hypothesis, sin cobertura                                                                                                                                                 |
| Superficie cubierta                | `vc/session.py` (keywords), `vc/guard.py` (denylist), `vc/attach.py` (staging)                                                                                                                                 |
| Superficie **NO** cubierta         | `vc/config.py` (parser de blacklist, flags), `vc/claudecli.py`, `vc/runtime.py`, `orb/orb_server.py` (routing/auth/token), `lk/agent.py`, `lk/wakeword.py`, `lk/claude_llm.py`, `vcctl.py`, `claude_daemon.py` |
| Ratio                              | ~11 tests sobre ~4.500 líneas de Python                                                                                                                                                                        |
| CI (`.github/workflows/tests.yml`) | `py_compile` de todo + `unittest tests.test_pure`. **Sin lint, sin typecheck, sin audit de dependencias, sin cobertura**                                                                                       |

### Security — estado actual

| Control                   | Estado real                                                                   | Observación                                                                                                                                                                           |
| ------------------------- | ----------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `vc/guard.py`             | Hook `PreToolUse` (Bash) con denylist de 15 regex catastróficos               | **Fail-open a propósito** (input raro → no bloquea). Denylist = frágil por diseño (bypass trivial: `rm -r -f`, variables, `$(...)`, base64)                                           |
| Permisos de Claude        | `--dangerously-skip-permissions` **por default** (`VOICE_CLAUDE_SAFE != "1"`) | god-mode: saga ejecuta lo que quiera. El guard es la única red                                                                                                                        |
| Superficie MCP            | Con `CLAUDE_PLUGINS=1`, los tools MCP (no-Bash) **no pasan por el guard**     | Gap ya identificado en Ciclo 5, nunca cerrado                                                                                                                                         |
| `orb_server` (HTTP :8777) | Bind a `127.0.0.1` ✅. `ORB_TOKEN` **vacío por default = sin auth**           | `POST /say` inyecta un turno de voz → llega a Claude en god-mode. Cualquier proceso local (o web page vía DNS-rebinding/CSRF, ya que no valida `Origin`/`Host`) puede disparar turnos |
| SSE `/events` + `_ok204`  | `Access-Control-Allow-Origin: *`                                              | Cualquier sitio web abierto en el browser puede leer el estado del orbe y hacer POST cross-origin                                                                                     |
| Adjunto de imagen         | Dead-drop en `/tmp` con `chmod 0o600` ✅                                      | OK                                                                                                                                                                                    |
| Secretos                  | `.env.local` gitignored ✅, keys nunca hardcodeadas ✅                        | OK                                                                                                                                                                                    |
| JWT LiveKit               | Minteo con `AccessToken` + `VideoGrants(room_join)` ✅                        | Sin TTL explícito (default del SDK), `identity`/`room` vienen del query sin validar                                                                                                   |
| Dependencias              | Sin `pip-audit` / Dependabot / SBOM                                           | Deps pesadas (livekit, onnxruntime, faster-whisper) sin escaneo de CVEs                                                                                                               |

**Lectura honesta**: la seguridad de saga hoy es **"local-only + un guard de denylist"**. Es razonable para una app personal en tu máquina, pero el framework AI-DLC tiene reglas de security baseline que van bastante más allá, y el testing está claramente por debajo de lo que el mismo framework pide (PBT extension, cobertura de lógica pura y serialización).

---

## Question 1: Extensión de Seguridad (opt-in del framework)

¿Se deben aplicar las reglas de la extensión SECURITY como restricciones bloqueantes en este proyecto?

**Nota**: si respondés A, cargo `security-baseline.md` completo y sus reglas pasan a ser _blocking findings_ — es decir, no cierro un stage con una regla aplicable incumplida. Dado que este ciclo ES sobre seguridad, A es lo coherente.

A) Sí — aplicar todas las reglas de SECURITY como restricciones bloqueantes (recomendado para aplicaciones production-grade)

B) No — saltear todas las reglas de SECURITY (apropiado para PoCs, prototipos y proyectos experimentales)

X) Otro (describir después del tag [Answer]:)

[Answer]: A

---

## Question 2: Extensión de Property-Based Testing (opt-in del framework)

¿Se deben aplicar las reglas de PBT (property-based testing) como restricciones bloqueantes?

**Nota**: PBT = en vez de escribir casos a mano, definís _propiedades_ que siempre deben valer y la librería (Hypothesis) genera cientos de inputs buscando romperlas. En saga aplica bien a: la denylist del guard (propiedad: "ningún comando catastrófico se cuela"), `normalize_state` del orbe (propiedad: siempre devuelve un estado válido), el parser de la blacklist JSON (propiedad: nunca crashea con JSON arbitrario), el round-trip base64 del socket de control. La deuda `R2` de `docs/tech-debt-plan.md` ya recomendaba PBT-partial.

A) Sí — aplicar todas las reglas de PBT como restricciones bloqueantes

B) Parcial — aplicar PBT solo a funciones puras y round-trips de serialización

C) No — saltear todas las reglas de PBT

X) Otro (describir después del tag [Answer]:)

[Answer]: A

---

## Question 3: Extensión de Resiliencia (opt-in del framework)

¿Se debe aplicar el baseline de resiliencia (AWS Well-Architected — Reliability Pillar)?

**Nota**: es una extensión orientada a workloads cloud (HA, DR, RTO/RPO, multi-AZ). saga es una app local de un solo usuario, sin cloud ni SLA. Mi lectura: la mayoría de las reglas darían N/A. Pero es tu llamada — hay una parte (observabilidad, degradación elegante, watchdogs) que sí aplica y saga ya practica a medias.

A) Sí — aplicar el baseline de resiliencia como guía de diseño

B) No — saltearlo (apropiado para proyectos locales/experimentales sin requisitos de disponibilidad)

X) Otro (describir después del tag [Answer]:)

[Answer]: B

---

## Question 4: Modelo de amenaza — ¿contra qué nos defendemos?

Esto define qué hallazgos son "reales" y cuáles son teatro. Sin esto, hardening = adivinar.

A) **Solo mishears y accidentes**: la amenaza es que saga malinterprete una orden de voz y ejecute algo destructivo. No hay atacante. Máquina personal de confianza. (= el modelo actual implícito del guard)

B) **Mishears + software local hostil**: además de A, asumimos que otro proceso/página web en la misma máquina puede intentar abusar de los endpoints locales de saga (`orb_server`, sockets Unix) para ejecutar código en god-mode. (= agrega auth local, CSRF/Origin, permisos de socket)

C) **A + B + prompt injection**: además, asumimos que contenido que saga _lee_ (una web, un archivo, un mail vía MCP) puede contener instrucciones que la secuestren y le hagan ejecutar acciones. (= el modelo más duro; implica repensar el god-mode)

X) Otro (describir después del tag [Answer]:)

[Answer]: C, quizas en vez de bypass permissions, podriamos setearla en auto mode

---

## Question 5: Alcance del ciclo — ¿auditoría o auditoría + fix?

El framework separa el diagnóstico de la ejecución. Elegí hasta dónde llega el Ciclo 9.

A) **Solo auditoría (documento)**: produzco el informe de hallazgos priorizados (testing + security) con recomendaciones y esfuerzo estimado. Cero código. Vos decidís después qué se implementa y en qué ciclo.

B) **Auditoría + fixes de bajo riesgo**: el informe, más implemento lo que es seguro y acotado (tests nuevos, endurecer CI con lint/typecheck/pip-audit, cerrar el CORS `*`, activar `ORB_TOKEN`). No toco el flujo de voz ni el god-mode.

C) **Auditoría + hardening completo**: todo lo de B, más los cambios estructurales que salgan del modelo de amenaza (ej. reemplazar la denylist por allowlist, gatear tools MCP, sandbox del god-mode). Riesgo real de regresión en el flujo de voz.

X) Otro (describir después del tag [Answer]:)

[Answer]: C

---

## Question 6: Presupuesto de latencia para la seguridad

Restricción dura histórica de saga: el turno de voz es ~2-2.5s y **no puede regresar** (NFR de todos los ciclos). Algunos controles de seguridad cuestan latencia por turno.

A) **Latencia intocable**: ningún control puede sumar latencia perceptible al turno de voz (>100ms). Los controles van en el arranque o en CI, no en el hot path.

B) **Tolerancia baja**: acepto hasta ~300ms extra por turno si el control cierra un riesgo real.

C) **La seguridad manda**: si un control importante cuesta latencia, se paga.

X) Otro (describir después del tag [Answer]:)

[Answer]: B, entiendo que cambios de seguridad NO DEBERIAN AFECTAR DEMACIADO EL RENDIMIENTO, esto debe mantenerse, pero soy algo tolerante, la seguridad es importante, pero para una ia agentica de voz en un localhost no deberia haber mucho problema

---

## Cómo responder

Completá el tag `[Answer]:` de cada pregunta con la letra (o `X` + tu descripción) y avisame. Si preferís que responda yo y siga, decilo — pero al ser un ciclo de seguridad, las Q4/Q5 son decisiones tuyas de verdad (definen qué es un bug y cuánto código toco).
