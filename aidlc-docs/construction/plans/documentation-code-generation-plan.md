# Code Generation Plan — Unit: documentation

**Unidad**: `documentation` (única; ver execution-plan.md). En esta etapa "generar código" significa
**escribir los archivos de documentación** en `docs/`. NO se genera ni modifica código de runtime.

**Fuente de verdad**: este plan. Las fuentes de contenido son el código real + los 9 artefactos de
Reverse Engineering (`aidlc-docs/inception/reverse-engineering/`) + el grafo (`graphify-out/`).

## Contexto de la unidad
- **Workspace root**: `/home/renzo/.local/share/saga` (de aidlc-state.md)
- **Project type**: Brownfield
- **Ubicación de salida**: `docs/` en la raíz del repo (NUNCA en aidlc-docs/). README raíz solo si es necesario.
- **Dependencias**: solo lectura del código y artefactos. Sin dependencias de orden entre archivos.
- **Requisitos cubiertos**: FR-1 (onboarding), FR-2 (referencia técnica), FR-3 (deuda+plan), FR-4 (ubicación).
- **Restricciones**: NFR-1 exactitud verificable, NFR-2 cero regresión, NFR-3 no duplicar CLAUDE.md/lk-README,
  NFR-5 Mermaid válido, NFR-6 sin secretos.

## Pasos de generación

- [x] **Step 1 — Crear `docs/architecture.md`**
  Arquitectura del sistema + las dos topologías (LiveKit default / clásico fallback), diagrama Mermaid,
  componentes y responsabilidades, integraciones (Deepgram, binarios), transporte (sockets + HTTP).
  Destila `reverse-engineering/architecture.md`. (FR-2.1)

- [x] **Step 2 — Crear `docs/turn-flow.md`**
  Flujo de un turno paso a paso en ambos modos (LiveKit: press→VAD/STT→Claude→TTS; clásico: _do_turn),
  cancelación/barge-in, visión on-demand, adjuntos del panel. Diagrama de secuencia Mermaid. (FR-1, FR-2.1)

- [x] **Step 3 — Crear `docs/internal-api.md`**
  Referencia de "APIs" internas: endpoints HTTP del orbe (/state, /events, /attach, /stage, /say),
  protocolos de los 3 sockets Unix (control, cerebro, whisper) con request/response, modelos de datos
  (session.json, mensaje stream-json, estados del orbe). Destila `reverse-engineering/api-documentation.md`. (FR-2.2, FR-2.3)

- [x] **Step 4 — Crear `docs/code-guide.md`**
  Recorrido archivo-por-archivo: un párrafo por módulo de `vc/`, `lk/`, daemons de raíz, `orb/`, qué hace
  y cómo encaja. Referencia el grafo `graphify-out/` y los docstrings para el detalle a nivel función
  (no se re-explica función por función). (FR-1.3 + inquietud "qué hace el código")

- [x] **Step 5 — Crear `docs/operations.md`**
  Operación: `saga-ctl start/stop/status/restart`, procesos por modo, logs (`saga.log`, monitor kitty ws10),
  variables de entorno, troubleshooting, y los **gotchas críticos** (plugins LiveKit en main thread,
  no `pkill -f claude`, el stack lo decide la key, single-owner, sRGB del bloom, beam>=3). Referencia
  `.claude/CLAUDE.md` y `lk/README.md` en vez de duplicarlos. (FR-1.4, NFR-3)

- [x] **Step 6 — Crear `docs/tech-debt-plan.md`**
  Deuda consolidada (duplicación clásico/LiveKit, `is_goodbye` huérfana, sin lint/typecheck/CI, LiveKit
  sin pin, `import os` duplicado en vc/app.py) + **plan de remediación priorizado** (impacto, esfuerzo,
  riesgo, orden). Incluye como recomendaciones: hardening de seguridad puntual y **PBT-partial** (Hypothesis)
  sobre funciones puras. **Solo plan, sin ejecutar.** (FR-3)

- [x] **Step 7 — Crear `docs/README.md` (índice + onboarding)**
  Puerta de entrada: qué es saga (resumen), setup/run mínimo (referenciando README raíz), y un índice
  que enlaza a los demás `docs/`, a los artefactos de RE (`aidlc-docs/inception/reverse-engineering/`)
  y al grafo (`graphify-out/`). Pega las piezas, no las duplica. (FR-1.1, FR-1.2)

- [x] **Step 8 — Link desde `README.md` raíz (solo si NECESARIO)**
  Evaluar si el README raíz necesita un puntero a `docs/`. Si sí, agregar una línea/sección breve
  (sin duplicar contenido). Si el README ya es suficiente, NO tocarlo. (FR-4.2)

- [x] **Step 9 — Resumen de generación (markdown)**
  Crear `aidlc-docs/construction/documentation/code/generation-summary.md` listando los archivos
  creados/modificados y el mapeo requisito→archivo. (handoff a Build & Test)

## Mapeo requisito → paso
| Requisito | Pasos |
|-----------|-------|
| FR-1 (onboarding) | 2, 4, 5, 7 |
| FR-2 (referencia técnica) | 1, 2, 3 |
| FR-3 (deuda + plan) | 6 |
| FR-4 (ubicación) | 7, 8 |

## Alcance estimado
- **Total pasos**: 9 (7 archivos en `docs/` + link condicional al README + resumen).
- **Archivos de runtime modificados**: 0 (a lo sumo `README.md` en Step 8). Cero regresión.
