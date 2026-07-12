# Code Generation Plan — Ciclo 5 (cargar plugins en Claude + observabilidad)

**Unit**: ciclo5-agentic (entregable único, brownfield single-component).
**Fuente de verdad**: este plan. La generación sigue estos pasos exactos, sin desviarse.

## Contexto y dependencias
- El daemon (`claude_daemon.py`) arma sus args con `build_claude_base_args()` de `vc/config.py`
  → **el toggle vive en config.py**; el daemon NO se toca.
- `prewarm_claude()` (`vc/claudecli.py:43`) lanza el daemon con `env={**os.environ}` → hereda el
  env completo → `VOICE_FULL_STACK=1 saga-ctl start` fluye solo hasta config. **`vcctl.py` NO se toca.**
- Estado actual: `CLAUDE_FAST_FLAGS = ["--setting-sources", "", "--disable-slash-commands"]`
  (+ guard vía `--settings` + claude-mem opt-in vía `--plugin-dir`).
- Verificación del flujo de voz/Win+Z = en vivo (usuario), Build&Test. Desde acá solo estático.

## Pasos

### Step 1 — Master switch (env) + blacklist (archivo) en `vc/config.py` (MODIFICAR)
- [x] env `VOICE_FULL_STACK`: **0** (default, claude a secas) / **1** (carga el stack). Solo prende/apaga.
- [x] blacklist `configs/plugins-blacklist.txt` (un `name@marketplace` por línea, `#`=comentario): qué plugins
  NO levantar. NO hardcode (el código lee el archivo). Reemplaza el hardcode `_DEFAULT_DISABLED` Y la env-csv
  `VOICE_DISABLED_PLUGINS`. Apaga el plugin ENTERO vía `enabledPlugins:false` en `--settings`, PER-SAGA.
- [x] `.saga-settings.json` (generado) lleva guard + enabledPlugins; reemplaza a `.guard-settings.json`.
- [x] Conservar `--dangerously-skip-permissions` (god-mode) + guard (`--settings`) en ambos modos.

### Step 2 — Log del modo activo (MODIFICAR config o daemon)
- [x] Emitir a `saga.log` qué modo de stack arrancó el daemon (off/full/selective) + las flags
  efectivas, para correlacionar con boot/TTFT en la medición. Reusar el `log()` existente.

### Step 3 — Harness de medición de atribución (CREAR `tools/measure_stack.py`)
- [x] Snapshot del árbol de procesos del daemon (`claude_daemon.py` → `claude` → MCPs nietos):
  por PPID recursivo, RSS (MB) + %CPU, etiquetado por cmdline (mapea cada MCP a su nombre).
- [x] Resumen: total RAM/CPU + top consumidores ordenados (lo que respondió "chroma ~900 MB" en vivo).
- [x] Parse de TTFT del `saga.log` (líneas de boot del daemon + TTFT por turno) → separar costo de
  boot (MCP startup) vs por-turno (hooks + tokens de skills).
- [x] Modo one-shot (snapshot) + `--watch N` (cada N s). Solo lectura (`ps`/`/proc`), sin tocar nada.
- [x] Degradación segura: si el daemon no corre, lo dice y sale 0.

### Step 4 — Doc operativo de la prueba (CREAR `aidlc-docs/construction/ciclo5-agentic/code/how-to-measure.md`)
- [x] Cómo prender el toggle (`VOICE_FULL_STACK=1 saga-ctl start`), correr `tools/measure_stack.py`,
  leer la atribución, y el árbol de decisión por síntoma (RAM/CPU→proceso · boot→`claude --debug` ·
  skills→tokens · hooks→latencia · "no detecta voz"→worker/contención). Criterio de abort (NFR1).

### Step 5 — Verificación estática (se ejecuta acá; se valida en Build&Test)
- [x] `py_compile` de `vc/config.py` + `tools/measure_stack.py`.
- [x] Imprimir `CLAUDE_FAST_FLAGS` en los 3 modos (off/full/selective) → confirmar que las flags
  cambian como se espera y el default queda idéntico al actual.
- [x] Import smoke (`vc.config`, `claude_daemon`) + `tools/measure_stack.py` corre sin daemon (no crashea).
- [x] `tests.test_pure` 11/11 (no regresión).

## Resumen
5 pasos. Modifica 1 archivo (`vc/config.py`, + log), crea 2 (`tools/measure_stack.py`,
`how-to-measure.md`). NO toca daemon, vcctl, worker, orbe. Reversible (default OFF). El entregable
del spike = toggle granular + harness de atribución + doc; la medición en vivo la corre el usuario.

## Trazabilidad
- FR1/FR3.2 → Step 1 (toggle granular) · FR3 → Step 2 (log) · FR3.1 → Step 3 (harness atribución) ·
  FR4 → Step 4 (doc + decisión) · NFR1/NFR3 → Step 5 (default idéntico, reversible) ·
  NFR2 → god-mode + guard intactos (Step 1).
