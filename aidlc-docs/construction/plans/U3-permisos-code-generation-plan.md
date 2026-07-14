# Plan — Code Generation: U3 (Modelo de permisos)

**Stage**: CONSTRUCTION → Code Generation (Part 1: plan) · **Unidad**: U3 · **Riesgo**: ALTO
**Rama**: `feature/ciclo9-u3-permisos`
**Entrada**: Functional Design (BR-U3-1…BR-U3-9, propiedades U3-P1…U3-P7) + NFR Requirements

> ⚠️ **Es la primera vez en U3 que se toca código de PRODUCCIÓN** — y es el código que decide si saga puede
> ejecutar algo o no. Un error acá no rompe un test: le abre la puerta a un `rm -rf` por voz, o deja a saga muda.

---

## 0. Orden de ejecución (deliberado)

**Primero el guard, después los args.** Motivo: si primero saco el god-mode y el guard todavía es evadible,
queda una ventana donde `auto` es la **única** capa. Se construye la red **antes** de sacar la otra.

1. Guard (capa 3, dura) → 2. System prompt (capa 2) → 3. Args (capa 1, saca el god-mode) → 4. Doctor → 5. Tests → 6. Docs.

---

## 1. Pasos

### Paso 1 — `vc/guard.py`: rewrite del cuerpo (FR2.2 · BR-U3-2, BR-U3-3, BR-U3-4)
- [ ] **1.1** — Parser: `_split_subcommands(line)` → separa por `;`, `&&`, `||`, `|`, newline (respetando comillas).
- [ ] **1.2** — Parser: `_parse(sub)` → `SubCommand(program, flags:set, args:list, raw:str)` con `shlex.split`.
      **Normalización de flags**: cortas agrupadas se expanden (`-rf` → `{r,f}`); largas conocidas mapean a su
      corta (`--recursive`→`r`, `--force`→`f`).
- [ ] **1.3** — Reglas estructurales (`program` + `flags` + `args`): `rm` recursivo-forzado · `mkfs*` · `dd of=/dev/` ·
      `shred`/`wipefs` · `chmod/chown -R /` · `truncate -s 0`.
- [ ] **1.4** — Reglas **de malas prácticas de git** (decisión explícita del usuario): `git reset --hard` ·
      `git push --force|-f` · `git clean -f`. **Bloqueo duro, sin confirmación.**
- [ ] **1.5** — **Se CONSERVA la denylist regex** (sobre el `raw` de cada subcomando) para lo que no se expresa
      como `program+flags`: pipe a shell (`curl|sh`), redirección a `/dev/sd*`, fork bomb, sobrescritura de
      dotfiles. **Y como fallback** si `shlex.split` explota.
- [ ] **1.6** — **`denied(cmd) -> str|None` mantiene su firma pública** (los tests de U1/U2 siguen valiendo).
- [ ] **1.7** — **`main()` fail-closed** (BR-U3-2): JSON inválido / `tool_name` ausente-o-no-str / `tool_input` no-dict /
      `command` no-str / **excepción inesperada** → `permissionDecision: deny` + log a `stderr`
      (el hook lo captura; nivel crítico para la excepción inesperada, que es un bug nuestro).
      `tool_name != "Bash"` → allow (fuera de jurisdicción).
- [ ] **1.8** — Docstring: reemplazar el párrafo *"Fail-open a propósito"* por el razonamiento invertido.

### Paso 2 — `vc/config.py`: system prompt (FR2.5 · FR2.6 · BR-U3-6, 7, 8)
- [ ] **2.1** — Agregar el bloque de seguridad al `CLAUDE_SYSTEM_PROMPT` (hoy: **cero líneas de seguridad**):
      **(a)** confirmación de **dos pasos** para lo destructivo/irreversible, con **verificación previa + readback**;
      **(b)** lo que saga **lee** son **datos, nunca órdenes** (anti prompt-injection);
      **(c)** **nada interactivo** (siempre flags no interactivos, nada de TUIs/pagers).
- [ ] **2.2** — **Calibrar la fricción** (riesgo R3, OWASP ASI09): enumerar **explícitamente** lo que NO se
      confirma (`ls`, `date`, leer, buscar, música, abrir apps, `git status/diff/log`). Si pide permiso para todo,
      el usuario la apaga → seguridad neta cero.
- [ ] **2.3** — **Sin romper el estilo**: el prompt es la voz de saga (texto plano, rioplatense, sin markdown por
      el TTS). El bloque nuevo respeta eso: la confirmación se **habla**, no se lista.

### Paso 3 — `vc/config.py`: args del CLI (FR2.1 · NFR3 · BR-U3-1)
- [ ] **3.1** — Eliminar la constante `CLAUDE_SKIP_PERMISSIONS` y el env **`VOICE_CLAUDE_SAFE`**.
- [ ] **3.2** — `build_claude_base_args()`: sacar `--dangerously-skip-permissions`, agregar
      **`--permission-mode auto` incondicional**.
- [ ] **3.3** — `_ensure_saga_settings()`: **NO** agregar bloque `permissions` (BR-U3-9) + **comentario** que
      explique el porqué, para que nadie lo "arregle" después.

### Paso 4 — `vc/doctor.py`: que no mienta (SECURITY-03)
- [ ] **4.1** — Reemplazar *"BYPASS activo (--dangerously-skip-permissions)"* por el estado real:
      `permission-mode auto` + **si el guard está cableado o no** (si `_ensure_saga_settings()` falló, la capa 3
      **no existe** → tiene que gritarlo, no callarse).

### Paso 5 — Tests (PBT-01 … PBT-10)
- [ ] **5.1** — `tests/generators.py`: generadores adversariales para las **formas equivalentes** de un comando
      catastrófico (permutaciones de flags: `-rf`, `-fr`, `-r -f`, `--recursive --force`, mezclas) + comandos de
      **malas prácticas de git** + `HookInput` malformado (JSON basura, tipos cruzados, no-ASCII, campos faltantes).
- [ ] **5.2** — **U3-P1** (catastrófico siempre bloqueado) → **des-marcar el xfail-strict `P7`**. Debe pasar a verde.
- [ ] **5.3** — **U3-P2** (benigno nunca bloqueado) → el test P8 existente **no puede regresar** (falsos positivos).
- [ ] **5.4** — **U3-P3** (fail-closed): ninguna entrada produce fail-open ni excepción no capturada.
- [ ] **5.5** — **U3-P4** (args sin god-mode, con `auto`, para toda combinación de env) →
      **des-marcar el xfail-strict `S1`**. Debe pasar a verde.
- [ ] **5.6** — **U3-P5** (equivalencia semántica de flags: las 4 formas de `rm -rf` dan el mismo veredicto).
- [ ] **5.7** — **U3-P6 (ORACLE, PBT-05)**: el guard **nuevo** bloquea **todo** lo que bloqueaba el **viejo**.
      Se congela la denylist regex de U2 como oracle → el rewrite **no puede abrir** un agujero que estaba tapado.
- [ ] **5.8** — **U3-P7**: el system prompt contiene las 3 reglas de seguridad (si alguien las borra, el test grita).
- [ ] **5.9** — Tests **example-based** (PBT-10): el settings generado **no** tiene bloque `permissions`; los
      casos concretos de bypass que Hypothesis encontró en U1 (`rm -r -f`, `rm --recursive --force`) quedan como
      **regresión permanente**.

### Paso 6 — Docs (la superficie que le miente al usuario)
- [ ] **6.1** — `README.md:161` y `docs/operations.md:66`: eliminar la fila de `VOICE_CLAUDE_SAFE` (ya no existe)
      y documentar el modelo de permisos real.
- [ ] **6.2** — `docs/tech-debt-plan.md`: cerrar la deuda *"considerar un modo no-god"* (U3 la resuelve) y
      registrar **D8** (el guard loguea el comando bloqueado) + **D9** (sandbox real, ciclo futuro).

### Paso 7 — Verificación estática (antes de cantar victoria)
- [ ] **7.1** — `pytest` completo: **47+ passed, 0 xfailed** (los 2 xfail-strict de U1/U2 tienen que **desaparecer**).
- [ ] **7.2** — `HYPOTHESIS_PROFILE=thorough` sobre las 4 propiedades de seguridad (U3-P1, P3, P5, P6).
- [ ] **7.3** — `ruff` limpio · `mypy` limpio sobre `vc/guard.py` + `vc/config.py` (typecheck estricto).
- [ ] **7.4** — **Benchmark del guard**: debe resolver en **< 50ms** (NFR de U3).
- [ ] **7.5** — Import smoke de los 3 procesos + `git diff --stat` (que no se coló nada fuera de scope).

---

## 2. Archivos

| Archivo | Tipo | Qué cambia |
|---|---|---|
| `vc/guard.py` | **PRODUCCIÓN** 🔴 | Rewrite del cuerpo: parser + fail-closed + git. **Misma firma pública.** |
| `vc/config.py` | **PRODUCCIÓN** 🔴 | System prompt (+bloque de seguridad) · args (`auto`, se va el god-mode) · settings (comentario) |
| `vc/doctor.py` | **PRODUCCIÓN** 🟡 | Que reporte el estado real |
| `tests/generators.py` | Test | Generadores adversariales de formas equivalentes + git + `HookInput` malformado |
| `tests/test_properties.py` | Test | U3-P1, P2, P3, P5, P6 · **des-marca xfail P7** |
| `tests/test_config.py` | Test | U3-P4, U3-P7 · **des-marca xfail S1** · settings sin `permissions` |
| `README.md`, `docs/operations.md`, `docs/tech-debt-plan.md` | Docs | `VOICE_CLAUDE_SAFE` ya no existe · D8/D9 |

**Fuera de scope (no se tocan)**: `lk/*`, `claude_daemon.py`, `vcctl.py`, `orb/*`, `vc/claudecli.py`.
(`claude_daemon.py` y `vc/claudecli.py` **consumen** `build_claude_base_args` → se benefician sin cambiar.)

---

## 3. Riesgos de esta ejecución y cómo se cubren

| Riesgo | Cobertura |
|---|---|
| **El rewrite del guard ABRE un agujero** que el regex tapaba | **U3-P6 (oracle)**: el viejo regex queda congelado como referencia. Es la propiedad más importante de U3. |
| **Falsos positivos**: el parser bloquea comandos legítimos → saga inútil | **U3-P2** + validación en vivo. Un guard que molesta es un guard que se desactiva. |
| **Fricción excesiva** del prompt (confirma todo) | Paso 2.2: enumerar explícitamente lo que NO se confirma. Se calibra en vivo. |
| **`_ensure_saga_settings()` falla** → sin guard | NFR4: se pierde la capa 3, **no todas** (`auto` no depende del settings). El `doctor` lo grita (Paso 4.1). |
| Sacar el god-mode y que saga **no pueda hacer nada** | Los 4 probes ya midieron que `auto` obedece las órdenes explícitas. Se confirma en vivo (G2). |
