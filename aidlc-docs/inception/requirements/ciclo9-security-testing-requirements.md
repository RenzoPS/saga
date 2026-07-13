# Ciclo 9 — Auditoría y hardening de Testing + Security · Requirements

**Fecha**: 2026-07-13
**Estado**: Requirements Analysis COMPLETO — pendiente de aprobación del usuario.
**Fuente de decisiones**: `ciclo9-security-testing-requirement-questions.md` (respondido por el usuario).

---

## 1. Intent Analysis

| Dimensión | Valor |
|---|---|
| **User request** | "Evaluá testing y security, a ver si está sólido, faltan tests, cambiarías algo. Ahora el framework es standard y se usa durante y antes de cada desarrollo; el framework tiene una gran metodología de seguridad y testing, es importante estar al día en ambas." |
| **Request type** | Enhancement + Refactoring (auditoría + hardening). No es feature nueva ni bugfix. |
| **Scope estimate** | **Multiple Components** — `vc/` (guard, config), `orb/` (server HTTP), `tests/`, `.github/workflows/`, `pyproject.toml`. NO toca el pipeline de voz (`lk/agent.py` salvo lo mínimo). |
| **Complexity** | **Moderate-Complex** — el hardening del god-mode toca el corazón de cómo saga ejecuta acciones. Riesgo real de regresión funcional (si Claude empieza a pedir permisos, el turno de voz se cuelga). |
| **Clarity** | Clara tras las respuestas del usuario. |
| **Depth** | **Comprehensive** (extensiones SECURITY y PBT activadas como bloqueantes → trazabilidad requerida). |

---

## 2. Decisiones del usuario (Requirements Questions)

| # | Pregunta | Respuesta | Consecuencia |
|---|---|---|---|
| Q1 | Extensión SECURITY | **A — Sí, bloqueante** | `security-baseline.md` CARGADO. Sus 15 reglas son *blocking findings*: ningún stage cierra con una regla aplicable incumplida. |
| Q2 | Extensión PBT | **A — Sí, bloqueante (full)** | `property-based-testing.md` CARGADO. Las 10 reglas PBT son bloqueantes (NO modo partial). Implica adoptar Hypothesis (PBT-09). |
| Q3 | Extensión RESILIENCY | **B — No** | `resiliency-baseline.md` NO cargado. No se evalúan sus reglas. |
| Q4 | Modelo de amenaza | **C — mishears + software local hostil + prompt injection**. Nota del usuario: *"quizás en vez de bypass permissions, podríamos setearla en auto mode"* | Modelo de amenaza más duro. La propuesta del usuario es **viable y verificada** (ver §4). |
| Q5 | Alcance | **C — Auditoría + hardening completo** | Se implementan los cambios estructurales, no solo el informe. |
| Q6 | Presupuesto de latencia | **B, CORREGIDO por el usuario (2026-07-13)**: *"no hay un máximo o mínimo, no quiero que haya latencia DETECTABLE. Hoy las respuestas y los turnos de voz (SIN PLUGINS) son RAPIDÍSIMOS, no quiero que ESO se joda"* | NFR1 reescrito: **cero latencia perceptible**. NO es un presupuesto de 300ms — es "no se debe notar la diferencia". Ver §6. |

### Correcciones del usuario posteriores a las respuestas iniciales (2026-07-13)

1. **Latencia (Q6) — se endurece**: mi lectura de "300ms" era incorrecta. El requisito real es **latencia no detectable por el usuario**. El baseline a preservar es el turno de voz actual **sin plugins** (`CLAUDE_PLUGINS=0`), que es el modo rápido (~1.5-2s TTFT). Un control de seguridad que haga perceptiblemente más lento el turno **se descarta o se rediseña**, no se "negocia" contra un presupuesto en ms. Esto reordena el diseño: los controles deben vivir en el **arranque** (flags, settings, reglas declarativas) o en **CI**, nunca en el hot path del turno.

2. **Reversibilidad (NFR3) — se elimina como toggle**: no habrá env var para "apagar la seguridad". Palabras del usuario: *"la reversibilidad la hacemos nosotros por git; el usuario tiene que gozar de la máxima seguridad al usar saga. No es reversible: es siempre 99% seguro (porque no existe nada 100% seguro en software)"*. Consecuencia: los controles de seguridad son **incondicionales en runtime**. La red de seguridad para el desarrollo es la **rama de git**, no un flag de producto. Se elimina el patrón "default OFF + opt-in" que usaron los ciclos anteriores.

3. **Rama de trabajo**: `feature/security-testing-aidlc-workflow` (creada 2026-07-13).

**Análisis de contradicciones/ambigüedades**: no se detectaron contradicciones. Q4=C (modelo duro) + Q6=B (latencia acotada) son compatibles: los controles propuestos actúan en el **arranque** (flags, settings) y en **CI**, no en el hot path del turno. El único control con costo por-tool-call es el hook PreToolUse, que ya existe hoy (~5-15ms, un `python3` corto) — el diseño debe evitar multiplicarlo.

---

## 3. Hallazgos de la auditoría (estado actual verificado en código)

### 3.1 Testing

| ID | Hallazgo | Severidad |
|---|---|---|
| T1 | Suite total = **11 tests / 3 clases** (`tests/test_pure.py`) sobre ~4.500 líneas. Cubre `session.py`, `guard.py`, `attach.py`. | Alta |
| T2 | **Cero tests** en: `vc/config.py` (parser de blacklist, construcción de flags), `orb/orb_server.py` (routing, auth, minteo de token, `normalize_state`), `vc/claudecli.py`, `vc/runtime.py`, `lk/*`, `vcctl.py`, `claude_daemon.py`. | Alta |
| T3 | **Sin PBT** (viola PBT-09: no hay framework seleccionado). Existen propiedades obvias sin testear: round-trip base64 del socket de control (PBT-02), invariante de `normalize_state` (PBT-03), idempotencia de `_ensure_saga_settings` (PBT-04), robustez del parser JSON de la blacklist. | **Bloqueante** (PBT-09, PBT-02, PBT-03) |
| T4 | CI sin **lint**, sin **typecheck**, sin **cobertura**, sin **audit de dependencias**. Solo `py_compile` + la suite. | Media (bloqueante por SECURITY-10) |
| T5 | La denylist del guard se testea con **8 ejemplos positivos y 8 negativos**. Para un control de seguridad basado en regex, es insuficiente: no hay búsqueda adversarial de bypasses. | Alta (SECURITY-11 defensa en profundidad) |

### 3.2 Security (mapeado a las reglas del baseline)

| ID | Hallazgo | Regla SECURITY | Severidad |
|---|---|---|---|
| S1 | **`--dangerously-skip-permissions` por default** (`vc/config.py:44,156`). saga ejecuta cualquier tool sin control, salvo el hook. Bajo el modelo de amenaza C (prompt injection), esto es el riesgo #1: contenido leído por saga (web, archivo, mail vía MCP) puede desencadenar acciones arbitrarias. | SECURITY-06 (least privilege), SECURITY-11 | **Crítica** |
| S2 | **Guard fail-open** (`vc/guard.py:52`): si el JSON de entrada no parsea, NO bloquea. Viola explícitamente "fail closed". | **SECURITY-15** | **Alta** |
| S3 | **Guard = denylist de regex**, evadible por construcción (`rm -r -f`, variables, `$(...)`, base64, `find -delete`). Es una defensa contra accidentes, no contra un adversario — y el modelo de amenaza ahora incluye adversario. | SECURITY-11 | **Alta** |
| S4 | **Tools MCP no pasan por el guard**: el matcher del hook es `"Bash"` únicamente. Con `CLAUDE_PLUGINS=1`, un tool MCP con efectos externos (escribir en el vault, mandar un mail, navegar) no tiene ningún control. | SECURITY-06, SECURITY-08 | **Alta** |
| S5 | **`orb_server` sin auth por default**: `ORB_TOKEN` vacío → `_authorized()` devuelve `True` (`orb/orb_server.py:110`). `POST /say` inyecta un turno que llega a Claude en god-mode. | **SECURITY-08** (deny by default) | **Crítica** |
| S6 | **CORS wildcard**: `Access-Control-Allow-Origin: *` en `_ok204()` y `/events` (`orb_server.py:188,283`). Sin validación de `Origin`/`Host` → una web abierta en el browser puede hacer POST cross-origin y disparar turnos (CSRF), y DNS-rebinding puede alcanzar el `127.0.0.1`. | **SECURITY-08** | **Crítica** |
| S7 | **Sin headers de seguridad HTTP** en el HTML servido (`orb.html`): falta CSP, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`. | **SECURITY-04** | Media |
| S8 | **Input validation ausente en los endpoints**: `identity`/`room` del `/token` vienen del query sin validar (largo, charset) y se firman en el JWT. `POST /attach` acepta cualquier body sin límite de tamaño (escribe a `/tmp` sin cap). Sin límite de `Content-Length`. | **SECURITY-05** | Alta |
| S9 | **Supply chain**: sin `pip-audit`/Dependabot, sin SBOM. `requirements.txt` es un `pip freeze` (lock ✅) pero `pyproject.toml` no pinea. Sin escaneo de CVEs sobre deps pesadas (livekit, onnxruntime, faster-whisper). | **SECURITY-10** | Alta |
| S10 | **JWT sin TTL explícito**: `AccessToken` usa el default del SDK (6h). Para un token que se emite a demanda por request, un TTL corto (minutos) es lo correcto. | SECURITY-12 (sesiones) | Media |
| S11 | **Sin rate limiting** en `orb_server`. `POST /say` es un endpoint que dispara trabajo caro (turno LLM completo). | SECURITY-11 | Media |
| S12 | **Logging sin control de secretos**: `saga.log` guarda el transcript completo de los turnos. No hay redacción. Si el usuario dicta una credencial por voz, queda en claro en disco. | SECURITY-03 | Media |
| S13 | Socket Unix de control (`LK_CTL_SOCK`) sin verificación de permisos explícita (hereda el umask). | SECURITY-06 | Baja |

**Reglas N/A** (sin superficie en saga): SECURITY-01 (no hay data store cifrable — no hay DB), SECURITY-02 (no hay LB/API GW/CDN), SECURITY-07 (no hay VPC/security groups; el bind a `127.0.0.1` es el equivalente y está OK), SECURITY-14 (no hay SIEM/alerting; app local monousuario). SECURITY-12 aplica solo parcialmente (no hay login de usuarios; sí aplica la parte de credenciales y sesiones/TTL).

---

## 4. Decisión de diseño clave: reemplazo del god-mode

**Propuesta del usuario (Q4)**: *"quizás en vez de bypass permissions, podríamos setearla en auto mode"*.

**VERIFICADO contra el CLI instalado (Claude Code 2.1.207, `claude --help`)** — no de memoria:

```
--permission-mode <mode>   (choices: "acceptEdits", "auto", "bypassPermissions", "manual", "dontAsk", "plan")
```

El modo **`auto` existe**. Es exactamente la primitiva que falta: auto-aprueba lo que el modelo evalúa como seguro y escala lo riesgoso, en vez de saltear el sistema de permisos entero. Confirma la intuición del usuario.

**Consecuencia arquitectónica**: hoy el guard (denylist propia, fail-open, evadible) es la ÚNICA defensa porque el bypass anula el sistema nativo. Con `auto`, el sistema de permisos nativo de Claude Code vuelve a estar en el circuito, y el guard pasa de ser *la* defensa a ser *una capa más* (defensa en profundidad, SECURITY-11).

### 4.1 Verificación completa de los permission modes (docs oficiales + CLI local)

Fuente: `code.claude.com/docs/en/permission-modes.md` + `claude --help` (v2.1.207). Verificado, no de memoria.

- **`auto` de la UI == `--permission-mode auto`**: el "auto mode on (shift+tab to cycle)" que aparece en la statusline es **el mismo mecanismo** que el flag/`defaultMode`. Una sola cosa, dos interfaces. (Confirmado contra la doc, a pedido del usuario.)
- **Semántica de `auto`**: *"Everything, with background safety checks"* — permite todo, pero un **clasificador** evalúa cada acción en segundo plano. Al entrar en `auto`, las *broad allow rules* que otorgan ejecución arbitraria (`Bash(*)`, `Bash(python*)`, `Agent`) **se descartan**; las reglas angostas (`Bash(npm test)`) se conservan. Las `permissions.deny` se respetan **siempre**, incluso en `auto`.
- **`auto` en no-interactivo**: *"In non-interactive mode with the `-p` flag, repeated blocks abort the session since there is no user to prompt."* Si el clasificador bloquea **3 veces seguidas o 20 en total**, la sesión **aborta** (no cuelga esperando input).
- **DATO CLAVE del entorno de saga**: el daemon **ya corre con `-p`** (`claude_daemon.py:60` → `build_claude_base_args(...) + ["-p", "--input-format", "stream-json"]`). Es decir, estamos exactamente en el caso documentado: **fail-closed por abort, no por cuelgue**. Esto elimina el riesgo de "turno colgado para siempre" que motivaba el bypass.
- **Alternativa evaluada y descartada — `dontAsk`**: auto-deniega todo lo que no esté en `permissions.allow`, sin clasificador (latencia cero, determinístico). Descartada por decisión del usuario (ver 4.2): limita demasiado lo que saga puede hacer.

### 4.2 DECISIÓN DEL USUARIO (2026-07-13): `auto` mode

> *"Yo probaría primero con auto mode on, dado que resuelve todo. Me parece bien que tenga juicio propio de lo que es raro o no, y en todo caso deberíamos cambiar el prompt inicial aclarando no dar nada interactivo, dada la naturaleza del proyecto."*

**Modo elegido: `--permission-mode auto`** (reemplaza a `--dangerously-skip-permissions`).

Rationale: `auto` preserva la utilidad agéntica completa de saga (no hay allowlist que la deje coja ante un pedido nuevo) y delega el juicio de "esto es raro" al clasificador nativo, en vez de a una denylist regex nuestra que ya sabemos que es evadible. `dontAsk` daba latencia cero pero al precio de que saga solo pueda hacer lo pre-aprobado.

**Riesgos asumidos y sus mitigaciones** (a implementar en Construction):

| Riesgo | Mitigación |
|---|---|
| **R-A: el clasificador suma latencia por acción** → choca con NFR1 (latencia no detectable) | **Se MIDE en Build&Test** (A/B contra el baseline actual sin plugins). Es el gate #1 del ciclo. Si la latencia se vuelve perceptible, el plan B es `dontAsk` + allowlist. NO se asume que es gratis. |
| **R-B: 3 bloqueos seguidos / 20 totales → aborta la sesión** (con `-p`) | El daemon ya respawnea con `--resume` ante muerte del proceso (contexto intacto). Verificar que el abort se maneje como muerte normal y no deje el turno colgado. |
| **R-C: comandos interactivos cuelgan el turno** (vim, pagers, `apt` sin `-y`, prompts de confirmación) — riesgo REAL e independiente de los permisos | **FR2.5 (nuevo, pedido del usuario)**: reforzar `CLAUDE_SYSTEM_PROMPT` con una regla dura: nunca ejecutar comandos interactivos ni que esperen input; usar siempre flags no interactivos (`-y`, `--no-pager`, `--yes`), redirigir a stdout, nada de TUIs. |
| **R-D: `auto` requiere que la cuenta cumpla los "auto mode requirements"** | Verificado disponible en la cuenta del usuario (el screenshot muestra `auto mode on` activo en su sesión). |

**Defensa en profundidad resultante** (SECURITY-11): permisos nativos (`auto` + clasificador) → reglas `permissions.deny` declarativas (se respetan incluso en `auto`) → guard hook fail-closed (FR2.2) extendido a MCP (FR2.3) → system prompt no-interactivo (FR2.5). Ninguna capa es la única.

---

## 5. Functional Requirements

### FR1 — Informe de auditoría (entregable documental)
- **FR1.1**: Documento de hallazgos priorizados (testing + security) con severidad, regla del baseline mapeada, y esfuerzo estimado. Base: §3 de este documento.

### FR2 — Hardening del modelo de permisos (S1, S2, S3, S4)

> #### ⭐ PRINCIPIO RECTOR (definido por el usuario, 2026-07-13) — "Orden EXPLÍCITA, no IMPLÍCITA"
>
> > *"Es imposible abarcar todos los casos; los MCPs tienen tools, obvio, pero hoy yo cuento con X plugins con sus respectivas tools, destructivas o no, y otros usuarios pueden contar con Y plugins con Z tools. No podemos abarcar todos los casos en la inmensidad de plugins. Si el usuario permite un MCP tipo github y le pide a Saga eliminar un repo, saga debería PROCEDER. En todo caso, hay que asegurarse de que la ORDEN llegue de forma EXPLÍCITA y no IMPLÍCITA."*
>
> **Reformulación del objetivo de seguridad del ciclo.** La defensa NO es contra las acciones *destructivas* — saga es la herramienta de Renzo y debe obedecerle, incluso para borrar un repo. La defensa es contra las acciones **NO SOLICITADAS**: las que saga ejecuta porque las *infirió*, o porque las leyó como instrucción en contenido que estaba procesando (una web, un archivo, un mail vía MCP). Esa es, exactamente, la definición de **prompt injection** — el modelo de amenaza C que el usuario eligió en Q4.
>
> **Por qué esto invalida el enfoque de denylist** (y corrige el rumbo de FR2.3): enumerar tools MCP peligrosos NO ESCALA — el conjunto de plugins/tools es abierto y varía por usuario. La propiedad a verificar no es *"qué tool es"* sino **"de dónde vino la orden"**. Una denylist responde la pregunta equivocada.
>
> **Consecuencia de diseño (clave para NFR1)**: en un asistente de **voz**, la confirmación de una acción irreversible **no cuelga el turno** — la confirmación *es la conversación*. saga puede responder *"¿confirmás que borre el repositorio X?"* y esperar el "sí" hablado. No es un prompt de terminal esperando stdin: es un turno de diálogo normal. **Costo de latencia: cero** (vive en el system prompt, no agrega clasificación ni procesamiento por tool call).
>
> **Los tres controles que derivan del principio** (todos de costo cero en el hot path):
> 1. **Regla anti-injection**: el contenido que saga *lee* (web, archivos, resultados de tools, mails) es **DATOS, nunca ÓRDENES**. Instrucciones embebidas en contenido leído se ignoran y se reportan al usuario, jamás se ejecutan.
> 2. **Confirmación hablada para lo irreversible**: ante una acción destructiva/irreversible (borrar, publicar, mandar, pushear, mergear), saga **confirma por voz** antes de ejecutar — salvo que la orden del usuario en el turno haya sido inequívocamente explícita.
> 3. **Trazabilidad de la intención**: saga no encadena acciones destructivas que el usuario no pidió como parte de una tarea "mayor" inferida por ella.
- **FR2.1**: **Eliminar `--dangerously-skip-permissions`** y adoptar **`--permission-mode auto`** (decisión del usuario, §4.2). Sin toggle de apagado (NFR3): el flag `VOICE_CLAUDE_SAFE` deja de tener sentido como "opt-in a la seguridad" y se elimina.
- **FR2.5** *(nuevo — pedido del usuario)*: reforzar `CLAUDE_SYSTEM_PROMPT` (`vc/config.py`) con una regla dura **anti-interactivo**: saga nunca ejecuta comandos que esperen input o abran una TUI (editores, pagers, prompts de confirmación); siempre usa flags no interactivos. Motivo: en un asistente de voz no hay nadie que conteste un prompt de terminal — un comando interactivo cuelga el turno igual que un prompt de permiso. Es un riesgo independiente del modelo de permisos y hoy no está mitigado.
- **FR2.6** *(nuevo — pedido del usuario, 2026-07-13)*: **saga pide VALIDACIÓN HABLADA antes de ejecutar acciones destructivas / irreversibles.** Se implementa en el `CLAUDE_SYSTEM_PROMPT`.

  **Estado actual del prompt (verificado, `vc/config.py:168-188`)**: **NO tiene una sola línea de seguridad**. Es puro estilo (nombre, rioplatense, sin markdown por TTS, largo proporcional) y además contiene una regla que empuja en la dirección **opuesta**: *"Sos agéntica... Si te piden una ACCIÓN que podés hacer en esta máquina, HACELA con la tool y después confirmá corto lo que hiciste. **No digas 'no puedo' si tenés cómo hacerlo**"*. Hoy el prompt es el acelerador; no hay freno.

  **Por qué esto encaja con las restricciones del ciclo**:
  - **No cuelga el turno** (a diferencia de un prompt de permiso o un comando interactivo): en voz, la validación **es un turno de diálogo normal**. saga pregunta, el usuario responde hablando. No hay stdin esperando.
  - **Costo de latencia: CERO** (NFR1). Vive en el system prompt, que ya se envía; no agrega clasificación ni procesamiento por tool call.
  - **No es una defensa contra el usuario** (respeta la aclaración de scope): no *impide* la acción destructiva — la **confirma**. Si el usuario dice que sí, saga procede.

  **Calibración (a definir en Functional Design de U3)**: la validación aplica solo a lo **destructivo / irreversible** (borrar, formatear, pushear con force, mergear, publicar, mandar, resetear historial). **NO** aplica a lo cotidiano (`ls`, `date`, leer, abrir una app, reproducir música) — si saga pide permiso para todo, se vuelve inusable y el usuario la apaga. El riesgo de diseño acá es el **exceso de fricción**, y se valida en vivo.

  **Relación con los otros controles** (defensa en profundidad, SECURITY-11): el prompt (FR2.6) es la capa de **intención**; el guard (FR2.2) es la capa de **último recurso** determinística para Bash catastrófico; `auto` (FR2.1) es la capa de **juicio** del modelo; `permissions.deny` (FR2.4) es la capa **declarativa** e inevitable. Ninguna sola alcanza: un prompt se puede ignorar, un regex se puede evadir.
- **FR2.2**: Convertir el guard de **fail-open a fail-closed** (SECURITY-15): input no parseable → denegar, no permitir.
- **FR2.3** *(REDEFINIDO por el usuario — Q4=C, 2026-07-13)*: **NO** se construye una denylist propia de tools MCP. Motivo (palabras del usuario): *"es imposible abarcar todos los casos... hoy yo cuento con X plugins con sus respectivas tools, otros usuarios pueden contar con Y plugins con Z tools. Si el usuario permite un MCP tipo github y le pide a Saga eliminar un repo, saga debería PROCEDER"*. Enumerar tools peligrosos no escala (el universo de plugins es abierto y varía por usuario) y además sería una defensa **contra el usuario**, no a su favor. La cobertura de MCP queda delegada al **clasificador nativo de `auto`** (que evalúa todas las tools, no solo Bash) + las reglas `permissions.deny` declarativas de FR2.4 para lo catastrófico. El guard propio se mantiene acotado a **Bash**, donde ya funciona.
- **FR2.4**: Definir reglas declarativas `permissions.deny` en `.saga-settings.json` para lo catastrófico/irreversible (se respetan **incluso en `auto`** — verificado en la doc; y no cuestan latencia porque son reglas, no clasificación).

**Alcance de la defensa (aclarado por el usuario, 2026-07-13)**: la defensa es contra **lo destructivo OBVIO** (accidentes, mishears, acciones catastróficas). **NO** se construye ninguna defensa *contra órdenes legítimas del usuario*: si Renzo pide una tarea destructiva y saga tiene el tool, saga la ejecuta — así debe funcionar. La garantía de que la orden llegó **de verdad** (explícita, del usuario real) se apoya hoy en la detección de voz y el wake word, y **se endurece en su propio ciclo** (Ciclo 6 — speaker verification, diferido). **Fuera de scope del Ciclo 9.**

### FR3 — Hardening de `orb_server` (S5, S6, S7, S8, S10, S11)
- **FR3.1**: Auth por default: generar `ORB_TOKEN` automáticamente si no existe (no puede quedar vacío = sin auth). Deny-by-default (SECURITY-08).
- **FR3.2**: Eliminar el CORS wildcard y validar `Origin`/`Host` (anti-CSRF, anti-DNS-rebinding).
- **FR3.3**: Headers de seguridad en el HTML (CSP, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`) — SECURITY-04.
- **FR3.4**: Validación de inputs: `identity`/`room` (charset + largo), límite de `Content-Length` en `/attach` y `/say` — SECURITY-05.
- **FR3.5**: TTL corto explícito en el JWT de LiveKit.
- **FR3.6**: Rate limiting básico en `/say` (endpoint que dispara trabajo caro).

### FR4 — Supply chain (S9)
- **FR4.1**: `pip-audit` en CI (escaneo de CVEs) — SECURITY-10.
- **FR4.2**: Evaluar SBOM y Dependabot.

### FR5 — Testing (T1–T5 + extensión PBT bloqueante)
- **FR5.1**: Adoptar **Hypothesis** como framework PBT (PBT-09), agregado a las deps.
- **FR5.2**: PBT de round-trip (PBT-02): base64 del socket de control; serialización del `.saga-settings.json`.
- **FR5.3**: PBT de invariantes (PBT-03): `normalize_state` siempre devuelve un estado válido; el parser de la blacklist nunca crashea con JSON arbitrario; **la denylist del guard nunca deja pasar un comando catastrófico generado adversarialmente**.
- **FR5.4**: PBT de idempotencia (PBT-04): `_ensure_saga_settings()` aplicado dos veces = una vez.
- **FR5.5**: Tests de ejemplo (example-based) para la superficie sin cobertura: `orb_server` (routing, auth, rechazo de CORS), `config.py` (flags según env). PBT-10: los PBT complementan, no reemplazan.
- **FR5.6**: Endurecer CI: lint (ruff), typecheck, `pip-audit`, y la suite completa con seed logging (PBT-08).

---

## 6. Non-Functional Requirements

| ID | NFR | Criterio de aceptación |
|---|---|---|
| **NFR1** | **Latencia NO DETECTABLE** (restricción #1 del ciclo, endurecida por el usuario) | El turno de voz **no debe sentirse más lento**. No hay presupuesto en ms que "gastar": el criterio es perceptual. **Baseline a preservar**: turno actual con `CLAUDE_PLUGINS=0` (el modo rápido, TTFT ~1.5-2s). Gate: benchmark A/B (antes/después) en Build&Test + **validación perceptual en vivo del usuario** ("¿se siente igual?"). Cualquier control que introduzca lentitud perceptible se **rediseña o se descarta** — no se negocia. Corolario de diseño: los controles viven en el **arranque** (flags, settings, reglas declarativas) o en **CI**; el hot path del turno no se toca. El único control por-tool-call es el hook PreToolUse, que **ya existe hoy** → el diseño no puede multiplicar su costo (nada de spawnear intérpretes extra por tool call). |
| NFR2 | **No regresión funcional** | El flujo de voz (Win+Z, wake, turno completo, cancel) sigue andando. Si `--permission-mode auto` cuelga turnos en modo no-interactivo, NO se adopta esa variante: se busca otra (ver §4). Validación en vivo del usuario. |
| **NFR3** | **Seguridad incondicional — SIN toggle de apagado** (reescrito por el usuario) | **NO** hay env var para desactivar la seguridad. El usuario final de saga goza siempre de la máxima protección; no existe un "modo inseguro" en el producto. La reversibilidad durante el desarrollo se gestiona **por git** (rama `feature/security-testing-aidlc-workflow`), no por config. Esto **rompe con el patrón de ciclos anteriores** ("default OFF + opt-in por env") y es deliberado. Ojo: esto NO prohíbe la *configurabilidad* de la política (ej. qué comandos permitir); prohíbe el interruptor que apaga el control entero. |
| NFR4 | **Fail-closed** (SECURITY-15) | Los controles de seguridad deniegan ante error/ambigüedad. Excepción documentada y acotada: un fallo de I/O al escribir el settings no debe brickear el arranque de saga — pero en ese caso **no se degrada a god-mode silencioso**: se arranca sin permisos elevados o se aborta con error visible (a definir en diseño). |
| NFR5 | **Defensa en profundidad** (SECURITY-11) | Ningún control es la única línea: permisos nativos (`auto`/`dontAsk`) + reglas declarativas deny/allow + guard hook + sandbox nativo (a evaluar). |

---

## 7. Compliance de extensiones (evaluación en Requirements)

### SECURITY (bloqueante)
Este stage produce un documento, no código. Las reglas se evalúan sobre el **sistema auditado**, y su incumplimiento actual es precisamente el output del stage (§3), no un blocker del stage en sí. Los blockers se aplicarán en Code Generation y Build&Test.

| Regla | Estado del sistema hoy | Se aborda en |
|---|---|---|
| SECURITY-01 | N/A (sin data store) | — |
| SECURITY-02 | N/A (sin LB/API GW/CDN) | — |
| SECURITY-03 | Parcial (logs sin redacción de secretos) | FR (deuda, S12) |
| SECURITY-04 | **No compliant** (sin headers) | FR3.3 |
| SECURITY-05 | **No compliant** (sin validación de inputs) | FR3.4 |
| SECURITY-06 | **No compliant** (god-mode, sin least privilege) | FR2.1, FR2.4 |
| SECURITY-07 | N/A (bind a loopback = equivalente OK) | — |
| SECURITY-08 | **No compliant** (sin auth, CORS `*`) | FR3.1, FR3.2 |
| SECURITY-09 | Parcial | FR3, FR4 |
| SECURITY-10 | **No compliant** (sin escaneo de CVEs) | FR4.1 |
| SECURITY-11 | **No compliant** (control único, sin rate limit) | FR2, FR3.6 |
| SECURITY-12 | Parcial (secretos OK; JWT sin TTL corto) | FR3.5 |
| SECURITY-13 | Parcial (vendor local, sin SRI — pero es local, no CDN) | A evaluar |
| SECURITY-14 | N/A (app local monousuario, sin SIEM) | — |
| SECURITY-15 | **No compliant** (guard fail-open) | FR2.2 |

### PBT (bloqueante, full)
| Regla | Estado hoy | Se aborda en |
|---|---|---|
| PBT-01 (identificación de propiedades) | No hecho | Functional Design del ciclo |
| PBT-02 (round-trip) | No compliant | FR5.2 |
| PBT-03 (invariantes) | No compliant | FR5.3 |
| PBT-04 (idempotencia) | No compliant | FR5.4 |
| PBT-05 (oracle) | Probable N/A (no hay implementación de referencia) | Se confirma en Functional Design |
| PBT-06 (stateful) | A evaluar (máquina de estados del orbe; sesión del daemon) | Functional Design |
| PBT-07 (calidad de generadores) | N/A hoy (no hay PBT) | FR5 |
| PBT-08 (shrinking + seed en CI) | No compliant | FR5.6 |
| PBT-09 (framework) | **No compliant** (no hay framework) | FR5.1 |
| PBT-10 (complementariedad) | N/A hoy | FR5.5 |

---

## 8. Resumen

saga tiene **higiene de secretos correcta** y **aislamiento de red razonable** (loopback), pero su postura de seguridad descansa en un único control frágil (denylist regex, fail-open) mientras corre en god-mode, y su superficie HTTP local no tiene autenticación ni protección CSRF. El testing cubre ~3 módulos de ~15 y no tiene PBT, que el framework ahora exige como bloqueante.

El hallazgo estructural del ciclo es que **`--permission-mode auto` existe** (verificado en el CLI 2.1.207) y permite salir del god-mode sin perder el flujo automático de voz — sujeto a verificación empírica en modo no-interactivo, que es el gate técnico central del Construction.
