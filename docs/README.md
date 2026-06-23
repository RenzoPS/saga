# Documentación de saga

Documentación para mantenedores: entender, operar y extender saga. Puerta de entrada e índice.

> **saga** — asistente de voz Linux/Hyprland: **voz → Claude Code → voz** sobre LiveKit + Deepgram,
> con un orbe 3D reactivo. **Default: transporte ROOM** (server LiveKit local + browser cliente + worker);
> fallbacks: `console` y clásico. El cerebro es Claude Code (ejecuta bash, lee archivos): *actúa* sobre la
> máquina, no solo conversa.

## Empezar

- Setup, run y stack: ver el [`README.md`](../README.md) de la raíz.
- Arranque rápido: `saga-ctl start` · uso: Win+Z (push-to-talk) · apagar: `saga-ctl stop`.

## Índice

| Documento | Para qué |
|-----------|----------|
| [architecture.md](architecture.md) | Cómo está armado: topología room (default) + fallbacks, componentes |
| [turn-flow.md](turn-flow.md) | Qué pasa paso a paso en un turno (room + clásico), turn detector, comandos de voz |
| [internal-api.md](internal-api.md) | Endpoints HTTP del orbe + protocolos de los 3 sockets + modelos de datos |
| [code-guide.md](code-guide.md) | Recorrido archivo por archivo: qué hace cada módulo |
| [operations.md](operations.md) | saga-ctl, procesos, logs, env, diagnóstico, gotchas críticos |
| [tech-debt-plan.md](tech-debt-plan.md) | Deuda técnica + plan de remediación priorizado |

## Otras fuentes en el repo

- **`lk/README.md`** — detalle del stack LiveKit/Deepgram.
- **Docstrings del código** — densos y confiables; la mejor fuente para el detalle a nivel función.

> [!note] Artefactos locales (no versionados)
> El proyecto se documenta/analiza con tooling de dev **local que no se commitea** (gitignored).
> Si los tenés en tu copia, complementan esta carpeta — pero no hacen falta para entender saga desde acá:
> - `aidlc-docs/` — análisis exhaustivo del workflow AI-DLC (9 artefactos de reverse-engineering + plan).
> - `graphify-out/` — grafo navegable del código generado con graphify (`graph.html`).

## Cómo se generó esta documentación

Producida con el workflow **AI-DLC** (tooling de dev local, no versionado). Esta carpeta (`docs/`)
es la documentación del repo, **autocontenida**: no depende de archivos gitignored. Restricción de
diseño: toda afirmación es verificable contra el código, y la documentación no modifica el runtime.
