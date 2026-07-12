# Ciclo 5 — saga agéntico (cargar plugins en Claude) — Requirements

## Intent Analysis

- **User request**: probar cómo reacciona el sistema de voz al cargar plugins (MCPs/skills/hooks)
  en el Claude del daemon, que hoy arranca *stripped*. Cambio de flag chico.
- **Request type**: Enhancement / Spike experimental (medición antes de comprometer).
- **Scope estimate**: Single component — `vc/config.py` (`CLAUDE_FAST_FLAGS`) + el arranque del
  `claude_daemon`. No toca worker, orbe, ni transporte.
- **Complexity estimate**: Moderate — el cambio de código es trivial, pero conlleva riesgo de
  boot storm (MCPs pesados) y superficie de seguridad (god-mode + tools con efectos externos).

## Reality-check arquitectónico (registrado)

- **U9 ≠ fix del boot storm.** U9 capeó la CPU del **worker** (wake ONNX, 410%→40%). El boot
  storm que abortó el spike previo venía de los **MCPs pesados del stack de Claude** (playwright
  lanza Chromium, npx baja paquetes, Google MCPs timeoutean) — los carga el `claude_daemon`,
  **otro proceso**. Cargas ortogonales. Hay más margen de CPU ahora, pero el costo de levantar
  los MCPs sigue intacto → por eso el ciclo **mide**.
- **Costos permanentes del stack** (aunque no haya boot storm): (1) arranque del daemon más
  lento (el strip bajó el primer token de ~57s a ~7s); (2) tool-definitions de cada MCP en el
  prompt → más tokens/latencia en CADA turno de voz.
- **MCPs que cargaría el full stack hoy** (los conectados a la sesión): Gmail, Google Calendar,
  Google Drive, exa, monton, obsidian-vault, claude-mem, context-mode, context7, github,
  playwright, vercel. Pesados/efectos-externos: playwright (Chromium), Google* (timeout +
  efectos), github, vercel.

## Functional Requirements

- **FR1 — Toggle reversible**: env var (default OFF) que conmuta el `claude_daemon` entre
  *stripped* (estado actual, óptimo post-Ciclo 7) y *con-plugins*. El arranque por defecto NO
  cambia. (Q3=A — patrón del spike `VOICE_FULL_STACK` previo, que fue revertido y se reimplementa.)
- **FR2 — Carga del stack**: cuando ON, dejar de pasar `--setting-sources ""` → el CLI carga
  user+project+local (todos los MCPs/skills/hooks). Full-stack-first como **instrumento de
  medición** del peor caso. (Q2=C resuelto: la lista no es input.)
- **FR3 — Instrumentación / medición**: capturar tiempo de arranque del daemon, TTFT por turno,
  y estabilidad del pipeline de voz. Reusar lo que YA existe (`claude_daemon.py` log de boot;
  `lk/agent.py` TTFT → `saga.log`). El test lo corre el usuario en vivo (Q1=A, PBT=No).
- **FR3.1 — Observabilidad de ATRIBUCIÓN (agregado tras objeción del usuario)**: el spike debe
  poder responder *qué pieza* es la culpable cuando algo falla, no solo *si* falla. El método
  difiere por TIPO de pieza:
  - **MCPs = procesos separados** (subproceso stdio del CLI, PPID rastreable) → RAM/CPU **directos**
    por proceso. Entregable: script de snapshot que camina el árbol de procesos del daemon claude y
    atribuye RSS/%CPU a cada MCP por su cmdline. (Medido en vivo: chroma-mcp de claude-mem ~900 MB;
    playwright ~196 MB; total stack ~1.9 GB / 15 procesos.)
  - **Boot lento / cuelgue del arranque** ("no carga Win+Z", "tarda en arrancar") → `claude --debug`
    loguea qué MCP conecta/timeoutea.
  - **Skills = tokens de contexto** (no procesos) → costo = system prompt inflado → comparar TTFT /
    tamaño de contexto con vs sin.
  - **Hooks = latencia por turno** (on-demand; claude-mem ya mete ~2s/turno) → delta de TTFT en `saga.log`.
  - **"No detecta la voz"** = worker/VAD, ortogonal al daemon → si aparece solo al cargar plugins, es
    contención de CPU (boot robando ciclos) → medir CPU del worker durante el boot.
- **FR3.2 — Master switch (env) + blacklist (archivo), a nivel PLUGIN, per-saga (rediseñado 2x por el usuario)**:
  - **env `VOICE_FULL_STACK`** = solo prende/apaga (0=claude a secas default · 1=carga el stack). NO lleva listas.
  - **blacklist `configs/plugins-blacklist.txt`** = qué plugins NO levantar (un `name@marketplace` por línea,
    `#`=comentario). Editable, versionable, escala a N. **NO hardcode**: el código lee el archivo (config), no
    una constante. Reemplaza tanto el hardcode `_DEFAULT_DISABLED` como la env-csv `VOICE_DISABLED_PLUGINS`.
  - Cada plugin de la blacklist se apaga **entero** (mcp+skills+hooks+slash) vía `enabledPlugins:false` en
    `--settings`, SOLO en el daemon de saga (aislado del global `~/.claude/settings.json`, reversible).
    VERIFICADO: el plugin desaparece de `claude mcp list` per-sesión. **Descartado** el modelo MCP-only
    (`--strict-mcp-config`) por abstracción equivocada.
- **FR4 — Entregable**: medición + decisión go/no-go. Si el full stack rompe, **identificar el plugin
  culpable con FR3.1** y agregarlo a `VOICE_DISABLED_PLUGINS` → re-medir. Recomendación final = set de
  plugins viables para voz.

## Non-Functional Requirements

- **NFR1 — Gate estabilidad + latencia (Q4=C, duro)**: (a) el pipeline de voz NO se cae (sin
  boot storm / inanición de CPU); (b) TTFT no regresa muy por encima del ~2-3s actual y el boot
  del daemon no se dispara. Violar (a) o (b) → **abort** del experimento.
- **NFR2 — Seguridad mínima (Q5 + SecurityExt=No)**: mantener god-mode
  (`--dangerously-skip-permissions`) + el guard PreToolUse actual (`vc/guard.py`) + regla dura
  en el system prompt. **Sin extensiones AI-DLC pesadas.**
  - **Hallazgo Q5**: el plugin que el usuario borró era **safety-net** (v0.8.2, marketplace
    `cc-marketplace`) = PreToolUse Bash hook anti-destructivo. **saga ya lo replica nativamente
    en `vc/guard.py`** (inyectado vía `--settings`, sobrevive al strip) → re-descargarlo sería
    redundante.
  - **Gap real a evaluar**: el guard cubre solo **Bash**. Cargar MCPs agrega tools con efectos
    externos NO-Bash (mandar mail, abrir browser) que el guard NO intercepta. Si el spike avanza
    a dejar plugins, evaluar extender el gating más allá de Bash (Construction).
- **NFR3 — Reversibilidad total**: default OFF; revertir = un env var. No degrada el arranque
  por defecto que quedó óptimo tras Ciclo 7 (~40% CPU / ~0.9 GB).

## Extension Configuration (decidido en Requirements)

| Extension | Enabled | Razón |
|---|---|---|
| Security Baseline | No | Exagerado; basta guard hook + regla dura en prompt (Q5/SecB) |
| Resiliency Baseline | No | Fuera de scope; no es AWS |
| Property-Based Testing | No | Es un prompt; el test lo mide el usuario en vivo + timestamp del log |

## Respuestas (trazabilidad)

Q1=A · Q2=C (→ full-first como instrumento, lista curada como salida) · Q3=A · Q4=C ·
Q5=guard nativo + prompt (sin re-descargar safety-net por redundancia) · SecB=No · Resiliency=No · PBT=No.

## Resumen

Spike reversible y acotado: un toggle env que carga el stack de plugins en el daemon de Claude,
para **medir** (boot, TTFT, estabilidad) si el boot storm sigue vivo post-Ciclo 7. Gate duro de
estabilidad + latencia; abort si rompe. Seguridad = lo que ya hay (guard.py = el safety-net que
se borró) + regla en prompt. Entregable = dato + decisión + (si aplica) lista curada de plugins.
