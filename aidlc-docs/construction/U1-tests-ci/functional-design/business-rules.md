# Business Rules — U1 (Red de tests + CI)

> En U1 las "reglas de negocio" son las **propiedades e invariantes** que el código de saga debe cumplir siempre. Este documento es el artefacto que **PBT-01** (regla bloqueante) exige: la lista de Testable Properties que se arrastra al Code Generation.

**Decisiones del stage**: pytest (Q1=B) · `pip-audit` bloqueante con allowlist (Q2=C) · bypasses del guard se registran y se difieren a U3 (Q3=A).

---

## Testable Properties (PBT-01)

### P1 — `normalize_state`: el estado del orbe siempre es válido
- **Regla**: para **cualquier** entrada (`str` arbitrario, vacío, Unicode, control chars, `None`), el resultado pertenece siempre a `VALID_STATES` = {`idle`, `rec`, `transcribe`, `screen`, `think`, `speak`, `nueva`, `error`, `cancel`, `attach`}. Nunca lanza excepción.
- **Categoría**: Invariante (range constraint) · **PBT-03**
- **Por qué importa**: el estado viaja por SSE al browser y maneja el render del orbe. Un estado inesperado deja el orbe en un limbo visual.
- **Generador**: estados válidos + inválidos + variantes (mayúsculas, espacios, sufijos) + `None` + texto arbitrario.

### P2 — `normalize_state` es idempotente
- **Regla**: `normalize_state(normalize_state(x)) == normalize_state(x)` para todo `x`.
- **Categoría**: Idempotencia · **PBT-04**

### P3 — Socket de control: round-trip base64
- **Regla**: `b64decode(b64encode(x)) == x` para bytes arbitrarios (incluye binario, vacío, UTF-8 multibyte).
- **Categoría**: Round-trip · **PBT-02**
- **Por qué importa**: los adjuntos de texto del usuario viajan por acá. Una pérdida en el round-trip corrompe el prompt.

### P4 — Socket de control: el framing no se puede romper ⚠️ **PROPIEDAD DE SEGURIDAD**
- **Regla**: para **cualquier** input, el payload base64 generado **no contiene `\n`** (`b"\n" not in b64encode(x)`).
- **Categoría**: Invariante (de seguridad) · **PBT-03**
- **Por qué importa** (esta es la propiedad más importante de U1): el protocolo del socket de control usa **`readline()` como framing** (`verbo <payload_b64>\n`). Si el payload pudiera contener un salto de línea, un adjunto malicioso **partiría el mensaje en dos e inyectaría un comando arbitrario en el socket del agente**. Hoy la propiedad se sostiene porque `base64.b64encode` (a diferencia de `base64.encodebytes`) no emite saltos de línea — pero eso es un detalle de implementación **implícito y no verificado**. Si alguien cambia esa llamada, el agujero se abre en silencio.
- **Nota de diseño**: la propiedad **verifica el contrato del framing**, no solo la librería. Es la clase de invariante que ningún test de ejemplo encuentra.

### P5 — El parser de la blacklist nunca crashea
- **Regla**: `_read_plugins_blacklist()` devuelve **siempre** una `list[str]` y **nunca** propaga una excepción, para cualquier contenido de archivo: JSON válido, JSON con tipos equivocados (`{"disabledPlugins": 42}`), JSON roto, binario, vacío, archivo inexistente. Degrada a `[]`.
- **Categoría**: Invariante (robustez) · **PBT-03**
- **Por qué importa**: esta función corre en el **arranque** de saga. Si lanza, saga no levanta.

### P6 — `_ensure_saga_settings` es idempotente
- **Regla**: aplicarlo dos veces produce el mismo settings que aplicarlo una vez (mismo contenido de `.saga-settings.json`).
- **Categoría**: Idempotencia · **PBT-04**

### P7 — El guard bloquea lo catastrófico ⚠️ **SE ESPERA QUE ESTA PROPIEDAD FALLE**
- **Regla**: para comandos generados desde las plantillas catastróficas conocidas, con variaciones realistas (espaciado, orden de flags, flags separados, comillas, rutas absolutas/relativas, `sudo` antepuesto), `denied()` devuelve una etiqueta (no `None`).
- **Categoría**: Invariante (de seguridad) · **PBT-03**
- **⚠️ EXPECTATIVA EXPLÍCITA (Q3=A)**: se **anticipa que este PBT encuentre bypasses** en la denylist actual. Ejemplo ya identificado a mano: `rm -r -f /` no matchea el regex `\brm\s+-[a-z]*r[a-z]*f` (que asume las flags juntas). **Eso es el PBT haciendo su trabajo, no un fallo del test.**
- **Alcance honesto**: un PBT **no puede demostrar la ausencia de bypasses** (el espacio de comandos shell es infinito y la denylist es evadible por construcción). Sirve para **encontrarlos**, no para certificar que no hay.
- **Manejo del hallazgo (decisión Q3=A)**: los bypasses encontrados se **registran** en el reporte de U1 y el test se marca como *expected failure* documentado. **El endurecimiento del guard es trabajo de U3** (FR2.2/FR2.4) — así U3 llega con una lista concreta y medida de qué cerrar, en vez de endurecer a ciegas. Cada bypass encontrado se convierte además en un **test de regresión permanente** (PBT-10).

### P8 — El guard NO bloquea lo legítimo (sin falsos positivos)
- **Regla**: para comandos benignos generados (`ls`, `cat`, `date`, `git status`, `git log`, `npm install`, `mkdir`, `rm archivo.txt`, `sudo pacman -S`), `denied()` devuelve `None`.
- **Categoría**: Invariante · **PBT-03**
- **Por qué importa**: un guard que traba trabajo legítimo se termina desactivando — y entonces no hay guard. Los falsos positivos son un riesgo de seguridad *indirecto pero real*.

### P9 — `attach`: máquina de estados y consume-once
- **Regla**: tras **cualquier secuencia** de `stage_text` / `clear_text` / `take_staged`, el estado observable coincide con un modelo de referencia simplificado. En particular: **consume-once** — dos `take_staged()` consecutivos nunca devuelven el mismo texto dos veces.
- **Categoría**: Stateful · **PBT-06**
- **Modelo de referencia**: un `Optional[str]` en memoria. `stage_text(t)` → `t.strip() or None`; `clear_text()` → `None`; `take_staged()` → devuelve el valor y lo pone en `None`.
- **Por qué importa**: si un adjunto se consume dos veces, el usuario ve su texto repetido en un turno que no lo pidió.

### P10 — Keywords de sesión: robustez y límites de palabra
- **Regla**: `is_reset_command` / `is_visual_command` nunca lanzan excepción para ningún string (Unicode, vacío, control chars, muy largo). Respetan límites de palabra: `is_visual_command("admira el cielo")` es `False` (no matchea el "mira" embebido).
- **Categoría**: Invariante · **PBT-03**

---

## Reglas de decisión (dominio de los generadores)

### Qué cuenta como "catastrófico" (para P7)
Lo que hoy declara la denylist (`vc/guard.py`), y que el generador debe cubrir con variaciones: borrado recursivo forzado · escritura directa a dispositivo de bloque · formateo de filesystem · fork bomb · pipe a shell desde la red · reescritura de historial git (`reset --hard`, `push --force`, `clean -f`) · sobrescritura de dotfiles de shell · destrucción de datos (`shred`, `wipefs`) · `chmod`/`chown -R` sobre `/` · truncado a cero.

### Qué cuenta como "benigno" (para P8)
Lectura, inspección, build, instalación de paquetes, git no destructivo, borrado de un archivo puntual. **Explícitamente NO se bloquea**: `sudo` per se, instalar paquetes, compilar, `git` normal.

---

## Reglas de Property-Based Testing (PBT-07, PBT-08, PBT-10)

- **PBT-07 (generadores de dominio)**: prohibido usar generadores primitivos crudos para tipos de dominio. `st.text()` jamás produciría un comando shell plausible. Se construyen generadores compositivos: **comando shell** (binario + flags + rutas + quoting + separadores), **estado del orbe**, **contenido de blacklist**. Se definen en un módulo reutilizable, no duplicados por archivo.
- **PBT-08 (shrinking + reproducibilidad)**: shrinking habilitado (default de Hypothesis, no se desactiva). En CI, la **seed se loguea en cada corrida** para poder reproducir el fallo exacto. Los fallos flaky se investigan, no se silencian.
- **PBT-10 (complementariedad)**: los PBT **no reemplazan** a los tests de ejemplo. Los 11 tests actuales se conservan. Los ejemplos fijan el comportamiento concreto conocido; las propiedades buscan lo desconocido. Todo contraejemplo que encuentre un PBT se agrega como test de ejemplo permanente.

## Reglas N/A (declaradas para no dejar huecos)

- **PBT-05 (Oracle)**: **N/A** — no existe implementación de referencia ni versión brute-force contra la cual comparar. Ningún componente de U1 es una optimización de un algoritmo conocido.
