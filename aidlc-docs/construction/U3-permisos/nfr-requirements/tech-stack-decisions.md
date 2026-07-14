# Tech Stack Decisions — U3 (Modelo de permisos)

**Decisión de fondo: CERO dependencias nuevas.** U3 hereda el stack de U1/U2 tal cual, y lo único que "agrega"
es un módulo de la **stdlib** (`shlex`).

---

## 1. Testing (PBT-09 — regla bloqueante)

| Herramienta | Estado | Decisión |
|---|---|---|
| **Hypothesis** | Ya adoptado (U1) | **Se hereda.** Los 4 requisitos de PBT-09 ya fueron verificados en U1: generadores custom, shrinking automático, reproducibilidad por seed, integración con el runner. **No se evalúa otro framework**: cambiarlo ahora sería reinventar sin motivo. |
| **pytest** | Ya adoptado (U1) | Se hereda. Corre los `unittest` viejos sin tocarlos. |
| **ruff / mypy / pip-audit** | Ya adoptados (U1) | Se heredan. `vc/guard.py` y `vc/config.py` están **ambos** dentro de los 3 módulos con **mypy estricto** (decisión Q3=C del Inception) → el rewrite del guard nace con typecheck. |

**Perfil `thorough` (1000+ ejemplos)** para las propiedades de seguridad de U3: **U3-P1**, **U3-P3**, **U3-P5**,
**U3-P6**. Es donde un bypass se esconde: 100 ejemplos no alcanzan para el espacio de formas de escribir `rm -rf`.

---

## 2. El parser del guard: `shlex` (stdlib) — decisión clave

**Necesidad concreta**: normalizar la sintaxis de un comando de shell para que el veredicto de seguridad **no
dependa de cómo se escribió** (`rm -rf` ≡ `rm -r -f` ≡ `rm --recursive --force`). Hoy son regex sobre el string
crudo, y **Hypothesis ya demostró que se evaden** (hallazgo F3 de U1).

**Antes de escribir código propio se buscó lo existente** (regla: no reinventar):

| Opción | Veredicto |
|---|---|
| **`shlex` (stdlib)** | ✅ **ELEGIDA.** Es el tokenizador de línea de comandos **de la stdlib de Python**, diseñado exactamente para esto (respeta comillas, escapes, POSIX). Cero dependencias, ya instalado, mantenido por CPython. |
| `bashlex` (PyPI) | ❌ Descartada. Es un parser **completo de la gramática de Bash** (AST real). Resolvería más casos (expansiones, subshells), pero: dependencia nueva, poco mantenida, y **sobra para el problema** — no necesitamos interpretar Bash, necesitamos clasificar. Contradice "la opción más simple que cumpla la tarea". |
| Sandbox real (bubblewrap, firejail, seccomp) | ❌ Fuera de scope de U3. Es la respuesta correcta a un modelo de amenaza más duro (*"containment en la capa de entorno primero"*, guía de Anthropic citada en la investigación), pero es **otro ciclo**: cambia la arquitectura de ejecución entera. **Se registra como deuda** para un ciclo futuro. |
| Seguir con regex, más largo | ❌ Descartada (decisión Q3). Tapa los 2 bypasses conocidos y deja el N+1. La propiedad P7 quedaría *"verde por ahora"*, no *"verde por construcción"*. |

**El regex NO se tira**: queda como (a) **fallback** cuando `shlex.split` falla (comillas sin cerrar → no se
asume benigno: se cae al regex, y si tampoco decide, **deny**), (b) **detector** de lo que no se expresa como
`program + flags` (pipes a shell, redirecciones a `/dev/sd*`, fork bomb), y (c) **oracle de no-regresión**
(propiedad **U3-P6**: todo lo que el regex viejo bloqueaba, el parser nuevo lo sigue bloqueando).

---

## 3. Modelo de permisos: `--permission-mode auto` (nativo del CLI)

**Verificado contra el binario instalado** (`claude --help`, v2.1.207), no de memoria:
`--permission-mode` acepta `acceptEdits`, `auto`, `bypassPermissions`, `manual`, `dontAsk`, `plan`.

| Alternativa | Veredicto |
|---|---|
| **`auto`** | ✅ **ELEGIDA** (decisión del usuario en el Inception: *"prefiero que saga tenga juicio propio"*). Cubre **todas** las tools, incluidas las de MCP — cosa que el guard (solo Bash) no puede. Medido: obedece las órdenes explícitas y **no cuelga** el turno. |
| `dontAsk` + allowlist | 🅱️ **Plan B** si el gate G1 (latencia) falla. Auto-deniega todo lo que no esté en `permissions.allow`. Costo predecible pero pierde el juicio del modelo. |
| `manual` | ❌ Sin TTY, "preguntar" **degrada a denegar** (medido, probe 4) → saga no podría hacer nada. |
| `bypassPermissions` | ❌ Es el god-mode actual. Es lo que U3 viene a sacar. |
| `permissions.deny` (reglas) | ❌ **Se deja VACÍO** (decisión del usuario, BR-U3-9): es un techo duro **inapelable** y rompería el principio de las dos veces. El techo duro vive en el **guard**, que es nuestro y auditable. |
| `permissions.ask` (reglas) | ❌ **Técnicamente inservible acá**: sin TTY **no pregunta, deniega** (medido). Es *por esto* que la confirmación de dos pasos vive en el **system prompt** y no en los permisos. |

---

## 4. La confirmación de dos pasos: el `CLAUDE_SYSTEM_PROMPT` (no hay alternativa técnica)

No es una preferencia de diseño, es **la única vía disponible**: el mecanismo nativo de permisos **no puede
preguntar sin TTY**. La confirmación tiene que ser **conversacional** (un turno de diálogo), que además es
**gratis** en latencia (el prompt ya se envía) y **no cuelga** nada (no espera stdin).

**Costo asumido y registrado** (riesgos R1/R2): es una capa **blanda** (juicio del modelo, evadible por prompt
injection). Por eso **no es la única**: el guard queda debajo para lo catastrófico y para las malas prácticas de
git.

---

## 5. Resumen

| | |
|---|---|
| **Dependencias nuevas** | **CERO** (`shlex` es stdlib) |
| **Herramientas de test nuevas** | **CERO** (Hypothesis heredado de U1) |
| **Archivos de producción tocados** | `vc/config.py` (args + prompt + settings), `vc/guard.py` (rewrite del cuerpo, **misma firma pública**), `vc/doctor.py` (que no mienta) |
| **Deuda declarada** | **D8** — el guard loguea el comando bloqueado (podría contener un secreto en la línea). No empeora lo actual (`saga.log` ya guarda el transcript). · **D9** — sandbox real de ejecución (bubblewrap/seccomp): la respuesta correcta a un modelo de amenaza más duro, es otro ciclo. |
