# Unit of Work Plan — Ciclo 4 (migración a room)

> Preguntas respondidas por el AI (usuario delegó). Solo documentación.

## Checklist
- [x] unit-of-work.md (6 unidades: U1 infra · U2 worker · U3 cliente audio · U4 wake cliente · U5 orbe sync · U6 saga-ctl)
- [x] unit-of-work-dependency.md (matriz + orden + hitos)
- [~] unit-of-work-story-map.md — N/A: este ciclo no generó user stories formales (refactor de infra). Las
      "capacidades" mapean 1:1 a las unidades (ver unit-of-work.md).
- [x] Validación de límites/dependencias

## Preguntas de decomposición (respondidas)

### Q1: Estrategia de agrupación de unidades
**[Answer]: Por CAPA del patrón LiveKit** (infra / backend-worker / frontend-cliente / orquestación). Es la
descomposición natural del patrón room y mantiene el seam limpio (cada unidad toca una capa).

### Q2: ¿Una unidad o varias?
**[Answer]: VARIAS (6).** Aunque saga es monolito modular, la migración toca capas separables con riesgos
distintos (infra Docker vs JS cliente vs Python worker). Descomponer permite construir/validar por partes
(ej: turno básico tras U1+U2+U3 antes de sumar wake/sync).

### Q3: Comunicación entre unidades
**[Answer]: Los mecanismos del diseño** — WebRTC (audio, vía room), Unix socket (Win+Z, cerebro), HTTP
(token/estado). Ninguno nuevo respecto al Application Design.

### Q4: ¿Deployment independiente?
**[Answer]: No microservicios** — sigue siendo un sistema local orquestado por saga-ctl. Las "unidades" son
de PLANIFICACIÓN (cómo dividir el trabajo), no servicios desplegables por separado.

### Q5: Orden / paralelizable
**[Answer]: U1 primero (base); luego U2+U3 en paralelo; luego U4+U5; U6 integra al final.** Ver
unit-of-work-dependency.md.
