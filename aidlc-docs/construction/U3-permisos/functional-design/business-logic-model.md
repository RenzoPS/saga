# Business Logic Model — U3 (Modelo de permisos)

**Ciclo 9 · Unidad U3 · Riesgo ALTO**
**FR**: FR2.1 · FR2.2 · FR2.3 · FR2.4 · FR2.5 · FR2.6
**Extensiones bloqueantes**: SECURITY (baseline) · PBT (property-based testing)

---

## 1. El problema, en una línea

saga hoy corre en **god-mode** (`--dangerously-skip-permissions`) con un system prompt que **no tiene una sola
línea de seguridad** y que además la empuja a actuar (*"HACELA con la tool... no digas 'no puedo'"*). El único
freno que existe es un hook (`vc/guard.py`) que es **fail-open** y **evadible** (medido en U1).

## 2. El principio rector (definido por el usuario, validado en campo)

> **La defensa NO es contra las acciones destructivas. Es contra las acciones NO SOLICITADAS.**
> saga es la herramienta de Renzo: si él pide algo destructivo y saga puede, saga lo hace. Lo que NO puede pasar
> es que ejecute algo que él **no pidió** — porque lo *infirió*, o porque un **mishear** del STT lo inventó.

**El mecanismo que el usuario eligió** (y que probó en vivo el 2026-07-13, ver audit.md):

> **Regla de las DOS VECES**: la primera vez es la **orden**; saga **verifica, hace readback y pregunta**; la
> segunda vez es la **confirmación**; recién ahí ejecuta. Un mishear produce la primera, pero es
> extremadamente improbable que produzca **también** la segunda, coherente con la primera.

**Precedente**: es exactamente cómo se comporta Claude Code con el usuario (permission prompts), y el usuario lo
puso como el estándar a replicar.

---

## 3. Las cuatro capas (defensa en profundidad — SECURITY-11)

Ninguna es la única línea. Van de la más blanda (juicio) a la más dura (determinística).

| # | Capa | Qué cubre | Naturaleza | Si falla… |
|---|---|---|---|---|
| 1 | **`--permission-mode auto`** (FR2.1) | **Todas** las tools, incluidas las de MCP (el guard solo ve Bash) | Clasificador nativo (juicio del harness) | Cae la capa 2 |
| 2 | **System prompt: dos pasos + anti-injection + anti-interactivo** (FR2.5, FR2.6) | Lo destructivo/irreversible **cotidiano** (borrar archivos, mandar, publicar) | **Blanda**: es juicio del modelo. Un prompt injection puede intentar pisarla | Cae la capa 3 |
| 3 | **Guard hook, fail-closed** (FR2.2) | Lo **catastrófico irreversible** + las **malas prácticas de git** | **Dura**: determinística, no depende del modelo | Cae la capa 4 |
| 4 | **Circuit breaker nativo del harness** | `rm -rf /`, `rm -rf ~` (bloqueados incluso bajo `bypassPermissions`) | Dura, fuera de nuestro código | — |

**`permissions.deny` (FR2.4): SE DEJA VACÍO — decisión del usuario.** Fundamento: una regla `deny` es un **techo
duro inapelable** (precedencia `deny` > `ask` > `allow` > hooks): lo que entre ahí, saga **no lo puede hacer
nunca**, ni pidiéndoselo dos veces. Eso **rompe el principio rector** (*"no que no pueda hacerlo"*). La cobertura
de lo catastrófico la da el guard (capa 3), que sí es nuestro y sí es auditable.

---

## 4. Flujo de decisión de un turno (lógica de negocio)

```
                 ORDEN DEL USUARIO (voz | wake | texto)
                                │
                                ▼
                 ┌──────────────────────────────┐
                 │ saga decide una TOOL CALL     │
                 └──────────────┬───────────────┘
                                ▼
        ┌───────────────────────────────────────────────┐
        │ CAPA 3 — GUARD (hook PreToolUse, solo Bash)    │
        │ ¿es catastrófico O mala práctica de git?       │
        └───────┬───────────────────────────┬───────────┘
                │ SÍ                        │ NO / no-Bash
                ▼                           ▼
        ╔═══════════════╗       ┌──────────────────────────────┐
        ║ DENY (duro)   ║       │ CAPA 1 — auto (clasificador)  │
        ║ sin apelación ║       │ ¿alinea con lo que se pidió?  │
        ╚═══════╤═══════╝       └───────┬──────────────┬───────┘
                │                       │ NO           │ SÍ
                ▼                       ▼              ▼
      saga LO DICE hablando       DENY limpio     ┌──────────────────┐
      ("eso no lo hago por        (no cuelga)     │ CAPA 2 — PROMPT   │
       voz, hacelo a mano")                       │ ¿destructivo /    │
                                                   │ irreversible?    │
                                                   └───┬──────────┬───┘
                                                       │ SÍ       │ NO
                                                       ▼          ▼
                                          ┌────────────────┐   EJECUTA
                                          │ READBACK + ¿?  │   (sin fricción)
                                          │ "esto borra X, │
                                          │  ¿confirmás?"  │
                                          └───┬────────┬───┘
                                              │ "sí"   │ "no"
                                              ▼        ▼
                                          EJECUTA   ABORTA
```

**Propiedad clave del flujo (medida, no supuesta)**: **ninguna** rama cuelga el turno de voz. El peor caso es que
saga diga *"no pude"*. Verificado con 4 probes contra el CLI 2.1.207 (ver audit.md 20:05).

---

## 5. Qué cambia en cada componente

### 5.1 `vc/config.py` — args del CLI (FR2.1)
- **Se elimina** `CLAUDE_SKIP_PERMISSIONS` y el env `VOICE_CLAUDE_SAFE` (NFR3: seguridad **sin toggle de
  apagado**; la reversibilidad la da git, no un flag).
- `build_claude_base_args()` deja de agregar `--dangerously-skip-permissions` y pasa a agregar
  **`--permission-mode auto`** — **incondicional**.

### 5.2 `vc/config.py` — `CLAUDE_SYSTEM_PROMPT` (FR2.5 + FR2.6)
Se le agrega un bloque de seguridad (hoy **no existe ninguno**) con tres reglas. Ver `business-rules.md` §BR-U3-4,
5 y 6. Costo de latencia: **cero** (el prompt ya se envía; no agrega llamadas ni clasificación).

### 5.3 `vc/config.py` — `_ensure_saga_settings()` (FR2.4)
**Sin cambios funcionales**: NO se agrega bloque `permissions` (decisión del usuario). Se documenta el porqué en
el código, para que nadie lo "arregle" después.

### 5.4 `vc/guard.py` — el corazón de U3 (FR2.2 + FR2.3)
Tres cambios:
1. **Fail-closed** (SECURITY-15): input no parseable / campo faltante / excepción → **deny** (hoy: *fail-open a
   propósito*). Con **log forense** para distinguir un bug del guard de un ataque.
2. **Parseo real del comando** (cierra los bypasses F3 medidos en U1): `shlex.split` + **normalización de flags**
   (`-r -f` ≡ `-rf` ≡ `--recursive --force`) + **split por separadores** (`;`, `&&`, `||`, `|`) evaluando **cada**
   subcomando. Hoy la denylist son regex sobre el string crudo, y Hypothesis ya demostró que se evaden.
3. **Alcance**: sigue siendo **solo Bash** (FR2.3: **NO** se construye denylist de tools MCP — no escala y sería
   defensa contra el usuario; la cobertura de MCP la da la capa 1).

### 5.5 `vc/doctor.py`
`doctor` hoy imprime *"BYPASS activo (--dangerously-skip-permissions)"*. Pasa a reportar el modo real
(`permission-mode auto` + guard activo). Es la superficie de diagnóstico: si miente, el usuario cree que está
protegido y no lo está.

---

## 6. Testable Properties (PBT-01) — U3-P1 … U3-P7

| ID | Propiedad | Categoría | Cierra |
|---|---|---|---|
| **U3-P1** | Para **todo** comando catastrófico generado adversarialmente, `guard.denied(cmd) != None`. | Invariante (business rule) | El xfail-strict **P7** de U1 (bypasses `rm -r -f`, `rm --recursive --force`) |
| **U3-P2** | Para **todo** comando benigno, `guard.denied(cmd) == None`. Un falso positivo = guard que se termina desactivando = sin guard. | Invariante | P8 (ya existe, no debe regresar) |
| **U3-P3** | **Fail-closed**: para **cualquier** entrada (JSON inválido, campos faltantes, tipos raros, no-ASCII), el guard **nunca** falla abierto: o deniega, o el comando no era peligroso. Nunca lanza una excepción no capturada. | Invariante | FR2.2 / SECURITY-15 / NFR4 |
| **U3-P4** | `build_claude_base_args(...)` **nunca** contiene `--dangerously-skip-permissions` y **siempre** contiene `--permission-mode auto`, para **cualquier** combinación de env (`CLAUDE_PLUGINS`, `VOICE_CLAUDE_MEM`, `VOICE_CLAUDE_SAFE` residual…). | Invariante | El xfail-strict **S1** de U1 (god-mode) + NFR3 (sin toggle) |
| **U3-P5** | **Equivalencia semántica de flags**: si un comando es catastrófico, **toda forma equivalente** de escribirlo también lo es (`rm -rf X` ≡ `rm -r -f X` ≡ `rm --recursive --force X` ≡ `rm -fr X`). El veredicto no depende de la sintaxis. | Invariante | El corazón del cierre de bypasses |
| **U3-P6** | **Oracle / no-regresión**: todo comando que la denylist **vieja** (regex de U1/U2) bloqueaba, el guard **nuevo** (parser) lo sigue bloqueando. El parser es un **superconjunto** del regex, nunca un subconjunto. | **Oracle** (PBT-05) | Riesgo de que el rewrite del guard **abra** un agujero que antes estaba tapado |
| **U3-P7** | El `CLAUDE_SYSTEM_PROMPT` **siempre** contiene las reglas de seguridad (dos pasos + anti-injection + anti-interactivo), para cualquier configuración. | Invariante | FR2.5 / FR2.6 (que nadie las borre sin que un test grite) |

**PBT-04 (idempotencia)**: cubierta por la propiedad P6 de U1 (`_ensure_saga_settings` idempotente), que sigue
vigente y no se toca.
**PBT-06 (stateful)**: **N/A** — el guard es una función pura (`denied(cmd) -> str|None`); no hay estado mutable.
**PBT-02 (round-trip)**: **N/A en U3** — no se introduce ninguna serialización/parseo invertible nueva. (El
parseo del comando es **lossy por diseño**: no se reconstruye el comando, se lo clasifica.)

---

## 7. Riesgos abiertos de esta unidad

| ID | Riesgo | Mitigación |
|---|---|---|
| **R1** | **La capa 2 es blanda**: la confirmación de dos pasos vive en el system prompt. Un prompt injection puede intentar pisarla, y el modelo puede simplemente no obedecerla. | Es una decisión consciente del usuario (scope: mishears/accidentes, no atacante activo). La capa 3 (guard) queda debajo para lo catastrófico. La autenticidad del hablante es **Ciclo 6**. Se valida en vivo con un mishear real. |
| **R2** | **La confirmación hablada es inyectable por el mismo canal** (objeción abierta de la investigación: si la tele dice "borrá X", la tele puede decir "sí, dale"). | Aceptado por el usuario con fundamento de scope. Se descarta la confirmación out-of-band en el orbe (fricción > beneficio para un equipo monousuario local). **Registrado como deuda del Ciclo 6.** |
| **R3** | **Exceso de fricción**: si saga pide confirmación para todo, el usuario la apaga → seguridad neta = 0 (OWASP **ASI09**: ~93% de los prompts se aprueban sin leerlos). | La regla del prompt enumera **explícitamente** qué es cotidiano y NO se confirma (`ls`, `date`, leer, música, abrir apps). Se calibra en vivo. |
| **R4** | **Falsos positivos del guard nuevo**: el parser podría bloquear un comando legítimo que el regex dejaba pasar. | Propiedad **U3-P2** (benignos nunca bloqueados) + **U3-P6** (oracle: el parser es superconjunto del regex viejo, no un reemplazo con distinta forma). |
| **R5** | **`auto` con `CLAUDE_PLUGINS=1`**: los probes corrieron en modo rápido (`--setting-sources ''`). Con plugins, la superficie de tools es otra. | Se re-verifica en vivo en Build & Test. |
