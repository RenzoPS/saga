# NFR Requirements — U3 (Modelo de permisos)

**Unidad**: U3 · **Riesgo**: ALTO · **Es la unidad que carga los gates duros del Ciclo 9.**

---

## 1. NFR1 — Latencia NO DETECTABLE (el gate G1) 🔴 EL GATE QUE PUEDE TUMBAR A U3

**Requisito** (definido por el usuario en el Inception, corrigiendo el "+300ms" original):
> La latencia del turno de voz debe ser **NO DETECTABLE** respecto del turno actual. No es un umbral en
> milisegundos: es un criterio **perceptual**, respaldado por un número.

**Baseline**: TTFT mediana **~2.09s** en modo rápido (`CLAUDE_PLUGINS=0`, 120 turnos del histórico de `saga.log`).
⚠️ El propio artefacto de U1 marca este baseline como **sucio** (histórico, condiciones mezcladas).

### Método de medición (Q1 = A + C)

| Fase | Qué | Cómo |
|---|---|---|
| **A — número** | A/B controlado **en la misma sesión y máquina** | N turnos idénticos con god-mode (`main`) vs N turnos idénticos con `auto` (rama U3). Se compara la **mediana del TTFT** (`[metrics] LLMMetrics ttft=` en `saga.log`). |
| **C — percepción** | El criterio de aceptación **real** | El usuario usa saga normalmente y responde: *"¿se siente igual?"* |

**Regla de resolución**: si divergen (el número sube pero no se siente), **manda la percepción** — NFR1 se definió
como *"no detectable"*, no como un umbral. La divergencia se **registra** en Build & Test.

### Señal temprana ya medida (no es el gate, pero descarta el desastre)
4 corridas alternadas del mismo prompt contra el CLI: `bypassPermissions` 11.14s / 7.74s vs `auto` 7.54s / 7.95s.
**Sin salto sistemático**: el ruido de red domina sobre cualquier costo del clasificador de `auto`.

### Por qué las capas de U3 son baratas por diseño
| Capa | Costo de latencia | Por qué |
|---|---|---|
| `--permission-mode auto` | **A medir** (es el único candidato real) | Es un clasificador nativo del harness. La señal temprana dice que no se nota. |
| System prompt (dos pasos, anti-injection, anti-interactivo) | **CERO** | El prompt **ya se envía** en cada turno. Agregar texto no agrega llamadas ni clasificación. Solo suma tokens de input (cacheados). |
| Guard fail-closed | **< 50ms** (requisito, ver §5) | Ya corre hoy en cada Bash. El parser reemplaza al regex dentro del **mismo** proceso. |
| `permissions.deny` | N/A | **Queda vacío** (decisión del usuario). |

**Plan B (si G1 falla)**: `--permission-mode dontAsk` + allowlist de lo cotidiano. Registrado en el Inception.
Con la evidencia actual **no se espera necesitarlo**.

---

## 2. NFR2 — No regresión funcional 🟢 RIESGO PRINCIPAL YA DESCARTADO (medido)

**Requisito**: el flujo de voz completo (Win+Z · wake "hey saga" · texto · turno · cancel) sigue andando.
El Inception fue explícito: *"si `--permission-mode auto` cuelga turnos en modo no-interactivo, NO se adopta"*.

**Estado**: **el riesgo se midió y no existe.** 4 probes contra el CLI 2.1.207 con los flags exactos del daemon:
ni el peor caso (un `ask` sin TTY) cuelga el turno — degrada a **denegación limpia** (`exit=0`, saga lo dice
hablando). El *"the run aborts"* de la doc de Claude Code aplica a prompts interactivos, no al path del daemon.

**Lo que queda por verificar en vivo** (no medible estáticamente):
- El turno de voz completo por las **3 vías** (texto, wake, Win+Z), como en U1 y U2.
- El **cancel** (Win+Z durante la respuesta).
- **`CLAUDE_PLUGINS=1`**: los probes corrieron en modo rápido (`--setting-sources ''`). Con plugins, la superficie
  de tools es otra (riesgo **R5** del Functional Design).

---

## 3. NFR3 — Seguridad incondicional, SIN toggle de apagado

**Requisito** (reescrito por el usuario en el Inception): **no existe** una env var que apague la seguridad.
El usuario final de saga goza **siempre** de la máxima protección. La reversibilidad la da **git**, no un flag.

**Impacto concreto en U3** (es *la* unidad donde este NFR se materializa):
- **`VOICE_CLAUDE_SAFE` se ELIMINA.** Era el opt-in *a* la seguridad (`=1` → modo seguro), o sea el patrón
  exactamente inverso al que el usuario decidió. Con U3, la seguridad es el default y no hay opt-out.
- `CLAUDE_SKIP_PERMISSIONS` (la constante) se elimina.
- `--permission-mode auto` se emite **incondicionalmente**.

**Verificación**: propiedad **U3-P4** (para **cualquier** combinación de env — incluida un `VOICE_CLAUDE_SAFE=1`
residual que alguien exporte de memoria — los args nunca traen `--dangerously-skip-permissions`).

**Rompe deliberadamente el patrón de los ciclos 4-8** ("default OFF + opt-in por env"). Es a propósito.

---

## 4. NFR4 — Fail-closed

**Requisito**: los controles deniegan ante error o ambigüedad. **Nunca fail-open.**

**Impacto en U3**: es la inversión de postura del guard (BR-U3-2). El guard hoy documenta su fail-open como una
virtud (*"no brickear el agente por un hiccup del hook"*) — ese razonamiento es el antipatrón exacto que
SECURITY-15 prohíbe: **la ruta del error es justo la que un atacante fuerza**.

**Excepción acotada y documentada** (viene del Inception): un fallo de I/O al escribir `.saga-settings.json` no
debe brickear el arranque de saga — **pero no se degrada a god-mode silencioso**. Comportamiento definido:
`_ensure_saga_settings()` devuelve `None` (ya lo hace hoy) → saga arranca **sin el guard cableado**, pero
**igual con `--permission-mode auto`** (que no depende del settings). O sea: se pierde la capa 3, **no** todas.
Y el `doctor` lo tiene que reportar (§6).

**Verificación**: propiedad **U3-P3** (ninguna entrada, por rara que sea, produce un fail-open ni una excepción
no capturada).

---

## 5. NFR5 — Defensa en profundidad (SECURITY-11)

**Requisito**: ningún control es la única línea.

**Cumplimiento en U3** (4 capas, ver `business-logic-model.md` §3): `auto` (todas las tools, incl. MCP) →
system prompt (dos pasos; **blanda**) → guard fail-closed (catastrófico + malas prácticas git; **dura**) →
circuit breaker nativo del harness.

**Requisito de performance del guard** (nuevo, propio de U3):
> El guard debe resolver en **< 50ms**. Corre como hook en un proceso `python3` nuevo en **cada tool call de
> Bash**. El costo dominante es el arranque del intérprete (~20-30ms), no el matching; `shlex.split` sobre una
> línea de comando es irrelevante frente a eso. **Se mide igual** en Build & Test (benchmark del hook aislado).

---

## 6. NFR de observabilidad (SECURITY-03) — la superficie de diagnóstico no puede mentir

`vc/doctor.py:76-77` hoy imprime *"BYPASS activo (--dangerously-skip-permissions)"* / *"modo seguro"*.
Tras U3 eso queda **falso**. Requisito: el `doctor` debe reportar el estado **real**:
- el permission-mode efectivo (`auto`),
- si el **guard está cableado** (si `_ensure_saga_settings()` falló, la capa 3 **no existe** → tiene que gritarlo).

**Sin secretos en el log** (SECURITY-03): el guard loguea el **label** del patrón bloqueado y el comando, no
tokens ni credenciales. (Riesgo residual conocido: un comando bloqueado podría contener un secreto en su línea
—ej. `curl -H "Authorization: ..."`—. Se registra como **deuda D8**, fuera de scope: hoy `saga.log` ya guarda el
transcript completo, así que U3 no empeora nada.)

---

## 7. NFR que NO aplican a esta unidad

| NFR | Estado | Motivo |
|---|---|---|
| Escalabilidad / capacidad | **N/A** | 1 usuario, 1 máquina, local. No hay carga que escalar. |
| Disponibilidad / DR / failover | **N/A** | Asistente local; si se cae, se levanta con `saga-ctl start`. |
| Usabilidad / accesibilidad | **Parcial** | Aplica indirecto vía el riesgo **R3** (exceso de fricción): si saga confirma todo, se vuelve inusable y el usuario la apaga → seguridad neta 0 (OWASP ASI09). Se valida en vivo. |
| Mantenibilidad | **Compliant** | ruff + mypy sobre `vc/guard.py` y `vc/config.py` (ambos están en los 3 módulos de seguridad con typecheck estricto, decisión Q3=C del Inception). |

---

## 8. Compliance PBT (PBT-09)

**Framework**: **Hypothesis** — ya adoptado en U1, con sus 4 requisitos verificados (generadores custom,
shrinking, seed-based reproducibility, integración con pytest). **U3 no introduce ninguna herramienta nueva.**

**Perfiles de ejecución** (heredados de U1):
- `default` (100 ejemplos) — CI.
- **`thorough` (1000+)** — para las propiedades de **seguridad**. En U3 entran acá: **U3-P1** (bloquea lo
  catastrófico), **U3-P3** (fail-closed), **U3-P5** (equivalencia de flags) y **U3-P6** (oracle de no-regresión).

**Seeds** (PBT-08): logueadas en cada corrida, como ya hace el CI desde U1.
