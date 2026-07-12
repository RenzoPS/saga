# Cómo correr la prueba del Ciclo 5 (cargar plugins + atribución)

Spike de medición: ver cómo reacciona el sistema de voz al cargar el stack de plugins en el
daemon de Claude, y **atribuir** cualquier falla a una pieza concreta.

## 1. Prender el toggle

**Master switch** = env `VOICE_FULL_STACK` (solo prende/apaga, NO lleva listas):

```bash
VOICE_FULL_STACK=1 saga-ctl restart    # carga el stack (menos la blacklist)
saga-ctl restart                       # default (0): claude a secas, sin plugins
```

**Qué plugins NO levantar** = blacklist en JSON, **editable**: `configs/plugins-blacklist.json`. Escala a N.

```json
{
  "disabledPlugins": [
    "playwright@claude-plugins-official"
  ]
}
```

Editás el archivo → `saga-ctl restart`. Cada plugin de la lista se apaga **entero** (mcp+skills+hooks+slash)
vía `enabledPlugins:false` en `--settings`, SOLO en el daemon de saga (per-sesión, NO toca tu
`~/.claude/settings.json`). El código es agnóstico: la lista es config, no hardcode.

Verificá el modo activo en el log:

```bash
rg "claude spawned" saga.log | tail -1     # muestra stack=off|full|selective + tiempo de boot
```

## 2. Medir la atribución

```bash
.venv/bin/python tools/measure_stack.py            # snapshot único
.venv/bin/python tools/measure_stack.py --watch 3  # vivo, cada 3s (durante el boot)
```

Da: RSS_MB + %CPU por proceso del árbol del daemon (cada MCP etiquetado), totales, loadavg del
sistema, y las últimas líneas de boot/stack/TTFT del saga.log.

## 3. Árbol de decisión por síntoma

| Síntoma | Quién mira | Cómo se atribuye |
|---|---|---|
| Mucha RAM | `measure_stack.py` | RSS por proceso → el MCP culpable (ej. chroma-mcp ~900 MB) |
| Mucho CPU / load alto | `measure_stack.py --watch` | %CPU por proceso + loadavg durante el boot |
| No carga Win+Z / tarda en arrancar | `claude --debug` (boot) | qué MCP conecta/timeoutea; + tiempo de `claude spawned` en saga.log |
| Tarda en responder | saga.log (TTFT) | separar boot (MCP startup) de por-turno (hooks + tokens de skills) |
| No detecta la voz | worker (ortogonal) | el VAD vive en el worker, no en el daemon; si pasa solo al cargar plugins = contención de CPU (el boot roba ciclos) → mirar %CPU del worker durante el boot |

Recordatorio de tipos: **MCPs** = procesos (RSS/CPU directos) · **skills** = tokens de contexto
(suben TTFT, no RSS) · **hooks** = latencia por turno (claude-mem ya mete ~2s/turno).

## 4. Criterio de abort (NFR1)

Abortar el experimento (volver a `saga-ctl restart` sin la env) si:
- el pipeline de voz se cae (boot storm / inanición de CPU), o
- el TTFT regresa muy por encima del ~2-3s actual o el boot del daemon se dispara.

Si rompe: identificar la pieza culpable con la tabla de arriba → agregar el plugin culpable a
`VOICE_DISABLED_PLUGINS` y re-medir.

## 5. Por qué el control es a nivel PLUGIN (verificado contra el CLI)

Un **plugin** agrupa mcp + skills + hooks + slash-commands. La unidad de activación de Claude Code es
el plugin (`enabledPlugins`), no la pieza suelta. Por eso saga apaga **plugins enteros**, no MCPs sueltos:
así no queda el mcp off pero los skills/hooks del mismo plugin colgados (sería inconsistente).

Mecanismo (verificado: con `--settings '{"enabledPlugins":{"X":false}}'`, X desaparece de `claude mcp list`
per-sesión, sin tocar el global): saga genera `.saga-settings.json` con `enabledPlugins:false` para los
plugins de `VOICE_DISABLED_PLUGINS` y lo inyecta vía `--settings` SOLO en su daemon.

| Tipo de control | Flag | Alcance |
|---|---|---|
| **Plugin entero** (lo que usamos) | `--settings enabledPlugins:false` | per-sesión, aislado, mcp+skills+hooks de una |
| MCP suelto | `--mcp-config` + `--strict-mcp-config` | solo MCPs (no skills/hooks) — NO lo usamos |
| Todas las skills | `--disable-slash-commands` | apaga todas |
| Todo el stack | `--setting-sources ''` | el strip del modo OFF |

Importante: el control es por plugin, NO por skill/hook individual (Claude Code no ofrece eso). Si un plugin
te interesa pero trae un hook caro, la única palanca es apagar el plugin entero o dejarlo entero.
