# Domain Entities — U3 (Modelo de permisos)

U3 no introduce persistencia ni modelos de datos nuevos. Las "entidades" son las estructuras que atraviesan la
decisión de permisos. Se documentan porque son **la superficie que los generadores de Hypothesis tienen que
producir** (PBT-07: generadores de dominio, no primitivos crudos).

---

## E1 — `HookInput` (el payload que Claude Code le pasa al guard por stdin)

Protocolo `PreToolUse` de Claude Code. **No lo definimos nosotros**: lo define el harness. El guard lo consume.

```jsonc
{
  "tool_name": "Bash",                 // string | ausente | tipo raro
  "tool_input": {
    "command": "rm -rf /",             // string | ausente | tipo raro
    "description": "..."               // ignorado por el guard
  }
}
```

| Campo | Tipo esperado | Qué hace el guard si viene mal (BR-U3-2) |
|---|---|---|
| (raíz) | objeto JSON | no parsea → **deny** |
| `tool_name` | `str` | ausente / no-str → **deny** |
| `tool_name != "Bash"` | — | **allow** (fuera de jurisdicción) |
| `tool_input` | `dict` | ausente / no-dict → **deny** |
| `tool_input.command` | `str` | ausente / no-str → **deny** |

**Generador PBT (U3-P3)**: JSON arbitrario, dicts con campos faltantes, tipos cruzados (int/list/dict donde va
str), strings no-ASCII, valores nulos. **Ninguna entrada puede producir una excepción no capturada ni un
fail-open.**

> Precedente que justifica la paranoia: en U2, `hmac.compare_digest` tiraba `TypeError` con no-ASCII → un token
> Unicode **crasheaba el handler** (fail-open por excepción). Lo cazó una propiedad, no un test de ejemplo.

---

## E2 — `ParsedCommand` (la abstracción NUEVA de U3, interna al guard)

Es lo que reemplaza al "string crudo + regex". **No se persiste**: vive dentro de `guard.denied()`.

```
Command(line: str)
  └── split por  ;  &&  ||  |  \n     →  [SubCommand, SubCommand, ...]

SubCommand
  ├── program : str            # "rm", "git", "dd", "mkfs.ext4"
  ├── flags   : set[str]       # {"r", "f"}  ← YA NORMALIZADO
  ├── args    : list[str]      # ["/", "~/Develop"]
  └── raw     : str            # el subcomando original (para el label y el fallback regex)
```

**Regla de normalización de flags** (el corazón de BR-U3-3):

| Entrada | `flags` resultante |
|---|---|
| `rm -rf X` | `{r, f}` |
| `rm -r -f X` | `{r, f}` |
| `rm -fr X` | `{r, f}` |
| `rm --recursive --force X` | `{r, f}` |
| `git push --force` | `{force}` (las largas sin corta conocida se guardan enteras) |
| `git push -f` | `{f}` → alias conocido de `force` para `git push` |

**Invariante (U3-P5)**: las cuatro primeras filas producen el **mismo** `flags` → el mismo veredicto. La
sintaxis no puede cambiar la decisión de seguridad.

**Entidad de veredicto**:

```
Verdict = str | None      # str = etiqueta legible del patrón catastrófico ("rm -rf: borrado recursivo forzado")
                          # None = no es catastrófico (pasa a las otras capas)
```

`guard.denied(cmd) -> Verdict` **se mantiene como función pura** (misma firma que hoy) → testeable sin stdin, y
los tests de U1/U2 siguen valiendo. **No es un rewrite de la interfaz, es un rewrite del cuerpo.**

---

## E3 — `DenyRule` (la denylist, ahora declarativa sobre `SubCommand`)

Hoy es `(regex, label)`. Pasa a ser una regla sobre la **estructura**, no sobre el texto.

| Familia | `program` | Condición | Label |
|---|---|---|---|
| Catastrófico | `rm` | `{r} ⊆ flags` **y** `{f} ⊆ flags` | borrado recursivo forzado |
| Catastrófico | `mkfs*` | siempre | formatear filesystem |
| Catastrófico | `dd` | algún arg matchea `of=/dev/` | dd escribiendo a disco |
| Catastrófico | `shred`, `wipefs` | siempre | destrucción de datos |
| Catastrófico | `chmod`, `chown` | `R ∈ flags` y target `/` | permisos recursivos sobre / |
| Catastrófico | `truncate` | `-s 0` | vaciar archivo |
| Catastrófico | (pipeline) | `curl\|wget` → `sh` | pipe a shell |
| Catastrófico | (redirección) | `> /dev/sd*\|nvme*\|…` | sobrescribir disco |
| Catastrófico | (shell) | fork bomb | fork bomb |
| Catastrófico | (redirección) | `>` / `>>` a dotfile de shell | sobrescribir dotfile |
| **Mala práctica git** | `git` | `reset` + `--hard` | git reset --hard |
| **Mala práctica git** | `git` | `push` + (`--force` \| `-f`) | git push --force |
| **Mala práctica git** | `git` | `clean` + `f ∈ flags` | git clean -f |

**Nota**: las tres últimas son la excepción explícita del usuario a la regla de las dos veces (BR-U3-4b). Las
formas que **no** se expresan naturalmente como `program + flags` (pipes, redirecciones, fork bomb) se siguen
detectando por **regex sobre el `raw`** — el parser **complementa** al regex, no lo reemplaza (y U3-P6 lo prueba:
oracle de no-regresión).

---

## E4 — `ClaudeArgs` (la línea de comandos del CLI)

Producida por `config.build_claude_base_args(session_id, flag) -> list[str]`. Consumida por
`claude_daemon.py:60` (daemon) y `vc/claudecli.py:159` (one-shot). **Fuente única.**

| Antes (hoy) | Después (U3) |
|---|---|
| `--dangerously-skip-permissions` (si `VOICE_CLAUDE_SAFE != "1"`) | **`--permission-mode auto`** (siempre) |
| `CLAUDE_SKIP_PERMISSIONS` (constante) | **eliminada** |
| `VOICE_CLAUDE_SAFE` (env) | **eliminada** (NFR3: sin toggle) |

**Invariante (U3-P4)**: para **toda** combinación de env, `"--dangerously-skip-permissions" not in args` y
`"--permission-mode" in args` con valor `"auto"`.

**Generador PBT**: combinaciones arbitrarias de `CLAUDE_PLUGINS`, `VOICE_CLAUDE_MEM`, `VOICE_CLAUDE_SAFE` (residual,
por si alguien la exporta de memoria), `VOICE_CLAUDE_MODEL`, y valores basura.

---

## E5 — `SagaSettings` (`.saga-settings.json`)

Settings aditivo del daemon (`--settings`), aislado del `~/.claude/settings.json` global.

```jsonc
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "Bash", "hooks": [{ "type": "command", "command": "python3 .../vc/guard.py" }] }
    ]
  },
  "enabledPlugins": { "algun-plugin@marketplace": false }   // solo si hay blacklist
  // NO hay bloque "permissions" — decisión del usuario (BR-U3-9)
}
```

**Invariantes** (heredadas de U1-P6, siguen vigentes):
- Idempotente: aplicarlo dos veces == una vez.
- El guard **siempre** queda cableado (`hooks.PreToolUse` nunca vacío).
- **Nuevo (U3)**: **no existe** la clave `permissions`.

---

## E6 — `SystemPrompt` (`CLAUDE_SYSTEM_PROMPT`)

Constante de `vc/config.py`. Hoy: identidad + estilo + *"HACELA... no digas 'no puedo'"*. **Cero seguridad.**

U3 le agrega un bloque de seguridad con 3 reglas (BR-U3-6, BR-U3-7, BR-U3-8). **Es una constante de texto**, pero
es **superficie de seguridad**: si alguien la edita y borra las reglas, no hay compilador que se queje.

**Invariante (U3-P7)**: el prompt contiene marcadores verificables de las tres reglas (confirmación de dos pasos,
contenido-como-datos, anti-interactivo). Un test lo afirma → borrarlas rompe el build.
