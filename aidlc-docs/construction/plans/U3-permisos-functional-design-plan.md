# Plan — Functional Design: U3 (Modelo de permisos)

**Ciclo**: 9 — Auditoría y hardening de Testing + Security
**Unidad**: U3 — Modelo de permisos (riesgo **ALTO**)
**Rama**: `feature/ciclo9-u3-permisos`
**Stage**: CONSTRUCTION → Functional Design (obligatorio por **PBT-01**)
**FR cubiertos**: FR2.1 · FR2.2 · FR2.3 · FR2.4 · FR2.5 · FR2.6
**NFR gate**: NFR1 (latencia no detectable) · NFR2 (no regresión) · NFR3 (sin toggle) · NFR4 (fail-closed) · NFR5 (defensa en profundidad)

---

## 0. Hechos verificados (no supuestos)

Todo lo de abajo se verificó contra el binario/código instalado, no de memoria.

- **`--permission-mode` acepta `auto`** — verificado contra `claude --help` en la versión instalada
  (**2.1.207**). Valores exactos: `acceptEdits`, `auto`, `bypassPermissions`, `manual`, `dontAsk`, `plan`.
  (Nota: la lista incluye `manual`, no `default`.)
- **Estado actual del código** (`vc/config.py`):
  - `CLAUDE_SKIP_PERMISSIONS = os.environ.get("VOICE_CLAUDE_SAFE") != "1"` → **god-mode por default**
    (`--dangerously-skip-permissions` se agrega en `build_claude_base_args`).
  - `CLAUDE_SYSTEM_PROMPT` **no tiene una sola línea de seguridad** — y sí tiene un acelerador:
    *"HACELA con la tool... No digas 'no puedo' si tenés cómo hacerlo"*.
  - `_ensure_saga_settings()` escribe `.saga-settings.json` con **solo** `hooks.PreToolUse` (el guard) +
    `enabledPlugins`. **No hay bloque `permissions`**.
- **Superficie de impacto** (grep, no memoria): `vc/config.py`, `vc/guard.py`, `vc/doctor.py:76-77`
  (imprime "BYPASS activo"), `README.md:161`, `docs/operations.md:66`, `docs/tech-debt-plan.md:89`,
  `tests/test_config.py`, `tests/test_properties.py`.
- **Consumidores de los args**: `claude_daemon.py:60` (daemon, `-p --input-format stream-json`) y
  `vc/claudecli.py:159` (one-shot). Fuente única: `build_claude_base_args`.
- **Red de tests que ya espera a U3** (xfail-strict → XPASS obliga a des-marcar):
  - `test_config.py::test_no_god_mode_by_default` (S1) → pasa cuando desaparece `--dangerously-skip-permissions`.
  - `test_properties.py::test_p7_blocks_catastrophic` (P7) → pasa cuando el guard deja de ser evadible.
- **Bypasses del guard MEDIDOS en U1** (hallazgo F3, no teoría): `rm -r -f` (flags separadas) y
  `rm --recursive --force` (forma larga) **no** matchean la denylist regex actual.

---

## 1. Pasos del Functional Design

- [x] **Paso 1 — Analizar el contexto de la unidad** (unit-of-work-ciclo9.md §U3 + requirements FR2)
- [x] **Paso 2 — Verificación empírica del comportamiento de `auto` en headless** (ver §3: es el
      riesgo #1 del ciclo y no puede diseñarse de memoria)
- [x] **Paso 3 — Preguntas al usuario** (§2 de este plan) y resolución de ambigüedades
- [x] **Paso 4 — Modelar la lógica de decisión de permisos** (las 4 capas y quién gana ante conflicto)
- [x] **Paso 5 — Diseñar el guard fail-closed** y el cierre de los bypasses (F3)
- [x] **Paso 6 — Diseñar las reglas `permissions.deny`** declarativas
- [x] **Paso 7 — Redactar las reglas de seguridad del `CLAUDE_SYSTEM_PROMPT`** (FR2.5 + FR2.6)
- [x] **Paso 8 — Identificar propiedades testeables (PBT-01)** → U3-P1…U3-Pn
- [x] **Paso 9 — Generar artefactos** (`business-logic-model.md`, `business-rules.md`, `domain-entities.md`)
- [x] **Paso 10 — Compliance de extensiones** (SECURITY + PBT) y mensaje de completitud

---

## 2. Preguntas al usuario

### Q1 — La objeción abierta: ¿por dónde se confirma lo irreversible?

Es **la** decisión de U3. Viene arrastrada de la investigación del estándar (§4.2 de los requirements) y se
difirió explícitamente hasta acá.

El problema: FR2.6 dice que saga **pregunta hablando** antes de una acción destructiva. Eso cuesta cero latencia
y no cuelga el turno. Pero si el vector de ataque es *"la tele / un podcast / otra persona dijo algo que el STT
transcribió"*, entonces **ese mismo canal puede decir "sí, dale"**. La confirmación hablada es inyectable por el
mismo canal que el ataque. Dato duro de Anthropic: **~93% de los permission prompts se aprueban sin leerlos**
(OWASP ASI09) → si confirmás todo, no confirmás nada.

Aclaración de scope que ya diste y sigue en pie: la autenticidad del hablante es **Ciclo 6** (speaker
verification), fuera de acá. La pregunta de U3 es más chica: **¿alcanza con la voz, o lo irreversible necesita
un gesto físico?**

- **A) Solo voz** (FR2.6 tal cual): saga pregunta hablando, el usuario contesta hablando. Costo cero, cero
  fricción física. Acepta el riesgo de la inyección por el canal de audio (mitigado a futuro en el Ciclo 6).
- **B) Voz + confirmación out-of-band en el orbe** para lo irreversible: saga dice *"che, esto borra X,
  confirmalo en el orbe"* y el orbe muestra el **comando exacto** (readback) con un botón/tecla. Sin el gesto
  físico, no se ejecuta. Cierra el bucle (el audio no puede apretar un botón), pero agrega fricción y **código
  nuevo** en orb_server + orb.html (endpoint de confirmación, estado de "pendiente", timeout).
- **C) Sin confirmación**: solo las capas determinísticas (guard + `permissions.deny` + `auto`). Lo catastrófico
  se bloquea de plano, lo demás se ejecuta. Cero fricción, cero código nuevo, pero el "borrá el repo X" que
  saga *infirió* no tiene freno intermedio.

**[Answer]**: **A — Solo voz (confirmación de DOS PASOS en el system prompt).** Decisión del usuario tras
probarlo EN VIVO (log de saga 17:13-17:15, ver audit.md): saga ya se detuvo, hizo readback ("encontré la carpeta,
solo tiene contra.txt") y esperó el "borralo" antes de ejecutar. Palabras del usuario: *"basta con pedir
confirmación y ya... Eso es lo que buscamos, NO que no pueda hacerlo"* + *"salvo que yo te lo pida DOS VECES
(la primera es la orden -> vos pedís confirmación -> confirmo -> ejecutás), vos no lo vas a hacer"*.
Se DESCARTA la confirmación out-of-band en el orbe (fricción > beneficio para un equipo monousuario local).
⚠️ CORRECCIÓN TÉCNICA ACEPTADA POR EL USUARIO: lo que vio es comportamiento EMERGENTE del modelo, no una regla —
el prompt actual no tiene ni una línea de seguridad y de hecho empuja al contrario. U3 lo convierte en REGLA
EXPLÍCITA (BR-U3-6). Y como saga NO tiene TTY, el mecanismo NATIVO de permisos no puede preguntar (medido: el
`ask` sin TTY DENIEGA, no pregunta) -> la confirmación SOLO puede vivir en el prompt. Es una capa BLANDA: por eso
el guard queda debajo como red dura (riesgo R1/R2 registrados).

---

### Q2 — Guard fail-closed: ¿hasta dónde llega el "closed"?

FR2.2 dice: input no parseable → **denegar**. Hoy el guard hace lo contrario (fail-open explícito: *"no brickear
el agente por un hiccup del hook"*).

El riesgo real de invertirlo: si el hook tiene un bug, o `python3` no está en el PATH del proceso que lo invoca,
o el JSON viene raro, **saga deja de poder correr cualquier comando Bash** — o sea, se rompe entera de una forma
difícil de diagnosticar (el usuario ve "no puedo hacer eso" y no sabe por qué).

- **A) Fail-closed estricto**: cualquier error del guard (JSON inválido, campo faltante, excepción) → `deny`
  con un motivo explícito y visible ("el guard no pudo evaluar el comando"). Es lo que pide SECURITY-15 al pie.
- **B) Fail-closed con distinción**: JSON inválido / campo faltante → `deny` (es la ruta que un atacante
  usaría). Excepción **inesperada** del propio guard (bug nuestro) → `deny` **y además** lo loguea fuerte.
  Diferencia con A: es la misma decisión de seguridad, pero deja rastro forense de "esto fue un bug, no un
  ataque". Sin toggle de escape (NFR3).
- **C) Fail-closed solo para Bash, con el resto intacto**: el guard ya solo mira `tool_name == "Bash"`; si el
  JSON no parsea no sabemos ni qué tool era → denegar igual (equivale a A en la práctica).

**[Answer]**: **A — Fail-closed + log forense.** (Asunción del AI, delegada y reportada al usuario; no
cambia el rumbo del diseño.) Cualquier error del guard deniega, y la excepción inesperada se loguea a nivel
crítico para distinguir un bug nuestro de un ataque. Ver BR-U3-2.

---

### Q3 — Cómo se cierran los bypasses del guard (F3, medido en U1)

Hoy la denylist es un array de regex sobre el string crudo del comando. Hypothesis ya demostró que es evadible
(`rm -r -f`, `rm --recursive --force`). Un regex más largo va a tapar esos dos y va a dejar el siguiente
(`rm -rf` con variables de shell, `$HOME`, comillas, `\`, `;`, sustitución de comandos…).

- **A) Endurecer los regex**: agregar los patrones que faltan. Barato, y mañana Hypothesis encuentra otro. La
  propiedad P7 seguiría siendo "verde por ahora", no "verde por construcción".
- **B) Parsear el comando de verdad** (`shlex.split` + análisis de tokens): normalizar flags (`-r -f` ≡ `-rf` ≡
  `--recursive --force`), separar por `;`/`&&`/`|` y evaluar **cada** comando. Es el enfoque que hace que P7
  pase por construcción y no por parche. Cuesta más código (y hay que cuidar los falsos positivos, P8).
- **C) Adelgazar el guard y delegar en `permissions.deny`**: dejar que las reglas nativas de Claude Code hagan el
  bloqueo (son inevitables y no las evade un regex nuestro), y que el guard quede como red secundaria.
  Depende de qué tan expresivas sean las reglas nativas (se está verificando: `Bash(rm:*)` y similares).

**[Answer]**: **B — Parsear el comando de verdad** (`shlex.split` + normalización de flags + split por
`;`/`&&`/`||`/`|`). (Asunción del AI, delegada y reportada.) Motivo: hace que la propiedad P7 pase POR
CONSTRUCCIÓN y no por parche — el regex tapa los 2 bypasses conocidos y deja el N+1. El regex heredado se
CONSERVA como fallback y como oracle de no-regresión (U3-P6). Ver BR-U3-3.

---

### Q4 — Qué entra en `permissions.deny` (la capa declarativa, FR2.4)

El probe #3 demostró que `permissions.deny` **funciona bajo `auto`, es inevitable y no cuelga el turno**: es la
capa más fuerte que tenemos (ni un hook la puede sobreescribir — la precedencia es `deny` > `ask` > `allow` >
hooks). La pregunta es **cuánto** ponemos ahí, porque lo que entre en `deny` **saga NO lo va a poder hacer nunca**,
ni aunque se lo pidas explícitamente por voz. Es un techo duro, no una confirmación.

Ojo con la tensión: en el probe #2, `auto` **borró el archivo** cuando se lo pediste. Eso es lo que vos querés
(*"si Renzo pide algo destructivo, saga lo ejecuta"*). Pero es exactamente lo que un **mishear** produciría.

- **A) `deny` mínimo — solo lo irreversible-catastrófico de sistema** (`rm -rf /`, `mkfs`, `dd of=/dev/*`,
  fork bomb, `shred`). El resto (borrar un archivo, `git push --force`) queda para el guard + la confirmación
  hablada. saga sigue pudiendo hacer casi todo por voz.
- **B) `deny` espejo del guard**: replicar en reglas declarativas lo mismo que hoy bloquea el guard (incluye
  `git reset --hard`, `git clean -f`, dotfiles). Defensa en profundidad real (SECURITY-11): si el hook falla o
  lo evaden, la regla nativa sigue. Costo: perdés esos comandos por voz **para siempre** (los hacés a mano).
- **C) `deny` espejo + cobertura MCP**: lo de B más reglas para lo irreversible de MCP que ya tenés instalado
  (ej. `mcp__plugin_github_github__merge_pull_request`, borrar repos). Contradice parcialmente tu Q4=C previo
  ("no denylist de MCP porque no escala"), pero acotado a lo **irreversible y obvio**, no a un catálogo.

**[Answer]**: **`permissions.deny` VACÍO** (ninguna de las 3 opciones tal cual: el usuario cambió la
premisa). Fundamento textual: *"Eso es lo que buscamos: NO que no pueda hacerlo"*. Una regla `deny` es un techo
duro inapelable (precedencia deny > ask > allow > hooks) y rompería el principio de las dos veces.
**EXCEPCIÓN EXPLÍCITA DEL USUARIO**: las **MALAS PRÁCTICAS DE GIT** (`git reset --hard`, `git push --force`,
`git clean -f`) quedan **BLOQUEADAS DURO EN EL GUARD**, sin confirmación posible — *"son, como su nombre indica,
MALAS PRÁCTICAS (además de comandos super destructivos)"*. O sea: el techo duro existe, pero vive en el guard
(nuestro, auditable, testeado), no en las reglas nativas. Ver BR-U3-4b y BR-U3-9.

---

## 3. El riesgo #1 del ciclo: MEDIDO, no supuesto ✅

La doc oficial de Claude Code (headless) dice que *"the run aborts"* cuando se intenta usar una tool que no está
pre-aprobada. Si eso valiera para el daemon de saga, `auto` **mataría el turno de voz** y NFR2 prohibiría
adoptarlo. Se midió con 4 probes reales contra el CLI (2.1.207), replicando los flags exactos del daemon
(`-p --output-format stream-json --verbose --include-partial-messages --setting-sources '' --disable-slash-commands`).

| # | Escenario | Resultado MEDIDO |
|---|---|---|
| 1 | `auto` + acción benigna (*"decime la hora"*) | Ejecutó `Bash(date)` **sin pedir permiso**. `exit=0`. |
| 2 | `auto` + acción **destructiva explícita** (*"borrá victima.txt"*) | **Ejecutó el `rm`.** El archivo se borró. `exit=0`. → `auto` **obedece la orden explícita del usuario** (alineado con el scope: saga no defiende al usuario de sí mismo). |
| 3 | `auto` + regla `permissions.deny: ["Bash(rm:*)"]` | **Bloqueado.** El archivo **NO** se borró. **El turno NO abortó** (`exit=0`): saga respondió hablando *"el sistema denegó el permiso..."*. El `result` trae `permission_denials[]`. |
| 4 | `auto` + regla `permissions.ask` **sin TTY** (el peor caso: el clasificador duda y no hay a quién preguntar) | **NO cuelga ni aborta.** El `ask` sin TTY degrada a **denegación limpia**: `exit=0`, el archivo no se borró, saga contestó *"no me otorgó permiso"*. |

**Conclusión de diseño (desbloquea U3)**: el modo `auto` **no puede colgar el turno de voz**. El peor caso no es
un cuelgue: es que saga diga *"no pude"*. Eso mueve el riesgo de **NFR2 (no regresión / cuelgue)** —que queda
descartado— a **G2 (utilidad)**, que se valida en vivo. El *"the run aborts"* de la doc aplica al caso de un
prompt interactivo, no al path que usa el daemon.

**Latencia (señal temprana, no el gate)**: 4 corridas alternadas del mismo prompt benigno →
`bypassPermissions` 11.14s / 7.74s vs `auto` 7.54s / 7.95s. **Sin salto sistemático**: el ruido de red domina
sobre cualquier costo del clasificador. No es el benchmark del gate G1 (ese se corre en Build & Test contra el
**baseline real del daemon: TTFT mediana ~2.09s**), pero descarta un salto grosero de `auto`.

⚠️ **Advertencia registrada**: el probe corrió con `--setting-sources ''` (sin plugins), igual que el daemon en
modo rápido. Con `CLAUDE_PLUGINS=1` la superficie de tools es otra y hay que re-verificar en vivo.

---

## 4. Compliance de extensiones (a completar al cierre del stage)

- **PBT-01**: identificar las propiedades testeables de U3 (guard, args, settings, prompt) → §Paso 8.
- **SECURITY-06** (least privilege) / **SECURITY-11** (defensa en profundidad) / **SECURITY-15** (fail-closed):
  son exactamente los FR de esta unidad; se evalúan en el mensaje de completitud.
