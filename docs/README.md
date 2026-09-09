# Documentación de saga

Documentación para mantenedores: entender, operar y extender saga. Puerta de entrada e índice.

> **saga** — asistente de voz Linux/Hyprland: **voz → Claude Code → voz** sobre LiveKit + Deepgram,
> con un orbe 3D reactivo. **Modo único de transporte: ROOM** (server LiveKit local + browser cliente
> + worker; el worker se despacha **por API** desde `/token`, ver `vc/dispatch.py`). El cerebro es
> Claude Code (ejecuta bash, lee archivos): *actúa* sobre la máquina, no solo conversa.

## Empezar

- Setup, run y stack: ver el [`README.md`](../README.md) de la raíz.
- Arranque rápido: `saga-ctl start` · uso: Win+Z · apagar: `saga-ctl stop`.
- Modo llamada (línea abierta, fin de turno por Flux): `SAGA_MODE=call saga-ctl start`.

## Índice

| Documento | Para qué |
|-----------|----------|
| [architecture.md](architecture.md) | Cómo está armado: topología room, componentes, dispatch, **quién es dueño del contexto** |
| [modo-llamada.md](modo-llamada.md) | El modo llamada: Flux, línea abierta, barge-in, interrupciones |
| [turn-flow.md](turn-flow.md) | Qué pasa paso a paso en un turno, turno segmentado, comandos de voz |
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
> - `aidlc-docs/` — bitácoras y artefactos de reverse-engineering del workflow AI-DLC.
> - `graphify-out/` — grafo navegable del código generado con graphify (`graph.html`).

## Cómo se generó esta documentación

Parte del desarrollo de saga se hizo con **[AI-DLC](https://github.com/awslabs/aidlc-workflows)**,
el framework de AWS Labs de ciclo de vida de desarrollo asistido por IA, ejecutado con **Claude Code**:
fases de inception y construction con gates de aprobación por etapa, y esta documentación como uno de
sus artefactos. Las bitácoras del framework son tooling de dev local y no se versionan.

Esta carpeta (`docs/`) es **autocontenida**: no depende de archivos gitignored. Restricción de
diseño: toda afirmación es verificable contra el código, y la documentación no modifica el runtime.
