# Requirements — saga (documentación del proyecto existente)

## Intent Analysis Summary

- **User Request**: "analizá y documentá este proyecto existente"
- **Request Type**: Documentación (sobre proyecto brownfield)
- **Scope Estimate**: System-wide (todo el sistema saga)
- **Complexity Estimate**: Moderate (sistema dual-modo LiveKit/clásico, multi-proceso)
- **Requirements Depth**: Standard

El análisis técnico ya se completó en la fase de Reverse Engineering (9 artefactos en
`aidlc-docs/inception/reverse-engineering/`). Estos requisitos definen el **entregable de
documentación humana** que se construye a partir de esos artefactos.

## Decisiones del usuario (de requirement-verification-questions.md)

| # | Pregunta | Respuesta |
|---|----------|-----------|
| Q1 | Objetivo del entregable | **D** — guía de onboarding (humano nuevo) + referencia técnica formal |
| Q2 | Tratamiento de deuda técnica | **B** — documentar + plan de remediación priorizado, **sin tocar código** |
| Q3 | Dónde vive la doc humana | **B** — carpeta `docs/` nueva; extender `README.md` solo si es NECESARIO |
| Q4 | Security extension | **B** — No (skip como gate; seguridad cubierta como contenido) |
| Q5 | Resiliency extension | **B** — No (AWS Well-Architected no aplica a app local) |
| Q6 | Property-Based Testing | **C** — No como gate; PBT-partial incluido como recomendación en el plan |

## Functional Requirements

### FR-1: Guía de onboarding para mantenedor nuevo
Producir documentación que permita a un dev que nunca vio el repo entender y extender saga:
qué es, cómo correrlo, cómo está estructurado, cómo fluye un turno de voz, y los gotchas críticos.
- **FR-1.1**: Overview del producto y de las dos topologías (LiveKit default / clásico fallback).
- **FR-1.2**: Setup/run reproducible (puede referenciar/consolidar lo del README + CLAUDE.md).
- **FR-1.3**: Mapa de componentes y responsabilidades (`vc/`, `lk/`, daemons, orbe).
- **FR-1.4**: Gotchas operativos críticos (plugins LiveKit en main thread, no `pkill -f claude`,
  el stack lo decide la key, single-owner, sRGB del bloom, beam>=3, etc.).

### FR-2: Referencia técnica formal
Documentación de referencia destilada de los artefactos de Reverse Engineering:
- **FR-2.1**: Diagrama(s) de arquitectura y de flujo de un turno (Mermaid).
- **FR-2.2**: Referencia de las "APIs" internas: endpoints HTTP del orbe + protocolos de los
  3 sockets Unix (control, cerebro, whisper) con su contrato request/response.
- **FR-2.3**: Modelos de datos (session.json, mensaje stream-json, word_aliases, estados del orbe).
- **FR-2.4**: Stack tecnológico y dependencias (directas + rol; binarios de sistema requeridos).

### FR-3: Documentación de deuda técnica + plan de remediación
- **FR-3.1**: Consolidar la deuda detectada (duplicación clásico/LiveKit, `is_goodbye` huérfana,
  sin lint/typecheck/CI, LiveKit sin pin en pyproject, `import os` duplicado en `vc/app.py`).
- **FR-3.2**: Plan priorizado: por cada ítem — impacto, esfuerzo estimado, riesgo, y orden sugerido.
  **Sin ejecutar cambios de código** (solo documento).
- **FR-3.3**: Incluir como recomendaciones futuras: hardening de seguridad puntual y adopción de
  **PBT-partial** (Hypothesis) sobre las funciones puras (`guard.denied`, limpieza/chunking TTS,
  keywords de sesión, consume-once de attach).

### FR-4: Ubicación y formato del entregable
- **FR-4.1**: Crear carpeta `docs/` en la raíz del repo con varios `.md`
  (ej: `architecture.md`, `turn-flow.md`, `operations.md`, `internal-api.md`, `tech-debt-plan.md`).
- **FR-4.2**: Extender `README.md` **solo si es necesario** (ej: link a `docs/`), sin duplicar contenido.
- **FR-4.3**: Texto en español (consistente con el repo). Diagramas en Mermaid válido.

## Non-Functional Requirements

- **NFR-1 (Exactitud)**: Toda afirmación de la doc debe ser verificable contra el código actual.
  Cero invención de paths, flags, comandos o contratos. (Ya aplicado en la review de RE.)
- **NFR-2 (No regresión)**: El entregable es **documentación**; NO debe modificar el comportamiento
  del runtime. No tocar `vc/`, `lk/`, daemons, `orb/` ni configs salvo, a lo sumo, `README.md`.
- **NFR-3 (Consistencia)**: No contradecir el manual operativo existente (`.claude/CLAUDE.md`,
  `lk/README.md`); donde haya solapamiento, referenciar en vez de duplicar.
- **NFR-4 (Mantenibilidad)**: Estructura modular en `docs/` (un archivo por tema) para que envejezca
  bien y sea fácil de actualizar pieza por pieza.
- **NFR-5 (Validez de contenido)**: Mermaid y ASCII validados antes de escribir (regla AI-DLC).
- **NFR-6 (Privacidad)**: No volcar secretos ni contenido de `.env.local` en la documentación.

## Out of Scope (este run)

- Cambios de código / fixes de la deuda técnica (Q2=B: solo plan, no ejecución).
- Activación de las extensiones Security/Resiliency/PBT como gates bloqueantes (todas opt-out).
- Refactors de la duplicación clásico/LiveKit (se documenta y planifica, no se ejecuta).
- Tests nuevos (PBT queda como recomendación, no se implementa).

## Key Requirements Summary

El entregable es **documentación humana en `docs/`** con dos caras (onboarding + referencia técnica),
más un **plan de remediación de deuda priorizado sin tocar código**. Restricción dura: exactitud
verificable contra el código y cero regresión de runtime. Las tres extensiones AI-DLC quedan
desactivadas como gates; seguridad y PBT-partial sobreviven como recomendaciones dentro del plan.
