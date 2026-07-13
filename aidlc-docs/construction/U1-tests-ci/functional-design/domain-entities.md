# Domain Entities — U1 (Red de tests + CI)

> saga no tiene entidades de negocio (no hay DB, no hay dominio comercial). Las "entidades" de U1 son las **estructuras de datos que los tests deben generar y verificar**. Este documento define sus formas y restricciones, que son la base de los generadores de dominio (PBT-07).

---

## E1 — Estado del Orbe

Enumeración cerrada de 10 valores. Fuente de verdad: `orb/orb_server.py` → `VALID_STATES`.

| Valor | Significado |
|---|---|
| `idle` | En reposo (estado por defecto y de fallback) |
| `rec` | Grabando |
| `transcribe` | Transcribiendo |
| `screen` | Capturando pantalla |
| `think` | Procesando (LLM) |
| `speak` | Hablando (TTS) |
| `nueva` | Sesión nueva |
| `error` | Error / "no te entendí" (amarillo) |
| `cancel` | Cancelado (rojo) |
| `attach` | Adjunto staged |

**Restricciones**: conjunto cerrado. Todo valor fuera del conjunto colapsa a `idle` (P1). `idle` es el elemento absorbente: es el default, el fallback y el estado al que vuelve el watchdog.

**Generador (PBT-07)**: mezcla de (a) los 10 válidos, (b) válidos con ruido (mayúsculas, espacios alrededor), (c) inválidos plausibles (`recording`, `idle2`), (d) texto arbitrario, (e) `None`, (f) vacío.

---

## E2 — Settings del daemon (`.saga-settings.json`)

Documento JSON que `vc/config.py` inyecta al daemon vía `--settings`. **Aislado del `~/.claude/settings.json` global** (no lo toca).

```json
{
  "hooks": {
    "PreToolUse": [
      {"matcher": "Bash", "hooks": [{"type": "command", "command": "python3 <ruta>/vc/guard.py"}]}
    ]
  },
  "enabledPlugins": {"<plugin>@<marketplace>": false}
}
```

**Restricciones**:
- `hooks.PreToolUse` **siempre presente** (es el cableado del guard).
- `enabledPlugins` presente **solo si** la blacklist no está vacía.
- Debe ser JSON válido y parseable siempre (si no, el daemon arranca sin guard).
- **Idempotente** (P6): generarlo dos veces produce el mismo contenido.

> **Nota para U3**: esta entidad va a crecer con `permissions.deny` (FR2.4). Su forma se redefine en el Functional Design de U3.

---

## E3 — Blacklist de plugins (`configs/plugins-blacklist.json`)

Config editable del usuario. Forma esperada:

```json
{"disabledPlugins": ["nombre@marketplace", "..."], "_comment": "ignorado"}
```

**Restricciones**:
- El parser (`_read_plugins_blacklist`) devuelve **siempre `list[str]`**, nunca lanza (P5).
- Entradas que no son `str` o que quedan vacías tras `.strip()` se descartan.
- Claves desconocidas (`_comment`) se ignoran.
- Archivo ausente, JSON roto, o raíz que no es un dict → `[]` (degradación segura, no excepción).

**Generador (PBT-07)**: JSON bien formado · JSON con `disabledPlugins` de tipo equivocado (int, string, null, lista de ints) · JSON sin la clave · raíz que es lista en vez de dict · JSON sintácticamente roto · bytes binarios · archivo vacío.

---

## E4 — Adjunto (Attach)

Estructura en dos partes con lifecycles distintos:

| Parte | Dónde vive | Lifecycle |
|---|---|---|
| **Texto** | Memoria del proceso agente (`_pending_text`) | Consume-once: `take_staged()` lo lee y lo limpia |
| **Imagen** | Dead-drop en `/tmp` (`ATTACH_IMG_PATH`, `chmod 0600`) | `take_staged()` devuelve la ruta pero **NO borra**; la borra el worker tras mandarla a Claude |

**Modelo de referencia (para el stateful PBT, P9)**: un `Optional[str]`.
- `stage_text(t)` → `t.strip() or None` (texto vacío limpia el staged)
- `clear_text()` → `None`
- `take_staged()` → devuelve el valor actual y deja `None`

**Invariante clave**: dos `take_staged()` consecutivos nunca devuelven el mismo texto dos veces (consume-once).

---

## E5 — Mensaje del socket de control

Protocolo de línea entre `orb_server` y el agente LiveKit:

```
<verbo> <payload_base64>\n
```

**Verbos**: `press` · `say` · `stage`
**Framing**: `readline()` — el `\n` es el delimitador.

**⚠️ Invariante de seguridad (P4)**: el payload base64 **nunca puede contener `\n`**. Si lo contuviera, el mensaje se partiría y la segunda mitad se interpretaría como un **comando nuevo** en el socket del agente → inyección de comandos. Se sostiene porque `base64.b64encode` no emite saltos de línea (a diferencia de `base64.encodebytes`), pero es un supuesto **implícito** que hoy nadie verifica.

**Generador (PBT-07)**: bytes arbitrarios · UTF-8 multibyte · texto con saltos de línea embebidos (el caso que motiva la propiedad) · vacío · payloads largos.

---

## E6 — Comando shell (entidad de los generadores del guard)

No es una estructura de saga, sino la **entidad de dominio de los generadores** de P7/P8. Composición:

```
[sudo] <binario> <flags> <operandos> [separador <otro comando>]
```

**Ejes de variación que el generador debe cubrir** (esto es lo que hace la diferencia entre un PBT útil y uno decorativo):
- **Flags juntas vs separadas**: `-rf` vs `-r -f` vs `-f -r` ← *el eje que expone el bypass ya conocido*
- **Espaciado**: espacios múltiples, tabs
- **Quoting**: `rm -rf "/path"`, `rm -rf '/path'`
- **Rutas**: absolutas, relativas, `~`, con espacios
- **Prefijos**: `sudo`, `env VAR=x`
- **Separadores**: `;`, `&&`, `||`, `|`
- **Formas largas**: `--recursive --force`

**Dos poblaciones distintas**: catastróficos (deben ser bloqueados, P7) y benignos (deben pasar, P8). El generador las produce por separado, con la lista de decisión de `business-rules.md`.
