# Requirements Clarification Questions

Tu pedido fue **"analizá y documentá este proyecto existente"**. El análisis ya se hizo
(Reverse Engineering, 9 artefactos en `aidlc-docs/inception/reverse-engineering/`). Estas
preguntas definen el **alcance del entregable de documentación** y la configuración de las
extensiones AI-DLC. Respondé poniendo la letra después de cada `[Answer]:`. Avisá cuando termines.

---

## Question 1

¿Cuál es el objetivo principal del entregable de documentación (además de los artefactos de Reverse Engineering ya generados)?

A) Solo los artefactos internos de AI-DLC que ya están (alcance cumplido, no hace falta más)

B) Documentación orientada a un humano nuevo que va a mantener/extender el repo (ej: README mejorado, guía de arquitectura, CONTRIBUTING)

C) Documentación de referencia técnica formal (API/sockets, diagramas, flujos detallados) destilada de los artefactos

D) Las dos anteriores (B + C): guía de onboarding + referencia técnica

X) Other (please describe after [Answer]: tag below)

[Answer]: D

---

## Question 2

¿Qué tan profundo querés que el entregable trate la **deuda técnica** detectada (duplicación clásico/LiveKit, `is_goodbye` huérfana, falta de lint/typecheck/CI, LiveKit sin pin)?

A) Solo dejarla documentada como está en `code-quality-assessment.md` (no proponer nada más)

B) Documentar + agregar un plan de remediación priorizado (qué atacar primero, esfuerzo, riesgo) — sin tocar código

C) Documentar + plan + empezar a ejecutar fixes en la fase de Construcción (implica cambiar código)

X) Other (please describe after [Answer]: tag below)

[Answer]: B

---

## Question 3

¿Dónde debería vivir la documentación humana final (si pediste B/C/D en Q1)?

A) Actualizar/expandir el `README.md` existente

B) Una carpeta `docs/` nueva en el repo (varios .md: arquitectura, flujos, operación)

C) Dejar todo dentro de `aidlc-docs/` (no tocar la raíz del repo)

D) No aplica (elegí Q1=A)

X) Other (please describe after [Answer]: tag below)

[Answer]: B "aunq tambien se podria extender el readme si es NECESARIO"

---

## Question 4: Security Extensions

Should security extension rules be enforced for this project?

A) Yes — enforce all SECURITY rules as blocking constraints (recommended for production-grade applications)

B) No — skip all SECURITY rules (suitable for PoCs, prototypes, and experimental projects)

X) Other (please describe after [Answer]: tag below)

[Answer]: B (aclarado con el usuario: scope = documentación + plan sin código; la seguridad ya está documentada en code-quality-assessment.md y se sigue cubriendo en el plan)

---

## Question 5: Resiliency Extensions

Should the resiliency baseline be applied to this project?

**Nota de contexto**: el resiliency baseline está derivado del **AWS Well-Architected Framework
(Reliability Pillar)**. saga es una app de escritorio local single-user, sin infra cloud/AWS, así
que buena parte de sus prácticas no aplican. Lo presento porque la regla AI-DLC lo exige, pero
para este proyecto probablemente quieras **B**.

A) Yes — apply the resiliency baseline as directional best practices and design-time guidance

B) No — skip the resiliency baseline (suitable for PoCs, prototypes, and experimental projects)

X) Other (please describe after [Answer]: tag below)

[Answer]: B (aclarado: resiliency baseline = AWS Well-Architected, no aplica a una app de escritorio local sin cloud)

---

## Question 6: Property-Based Testing Extension

Should property-based testing (PBT) rules be enforced for this project?

A) Yes — enforce all PBT rules as blocking constraints (recommended for projects with business logic, data transformations, serialization, or stateful components)

B) Partial — enforce PBT rules only for pure functions and serialization round-trips (suitable for projects with limited algorithmic complexity)

C) No — skip all PBT rules (suitable for simple CRUD applications, UI-only projects, or thin integration layers with no significant business logic)

X) Other (please describe after [Answer]: tag below)

[Answer]: C (aclarado: PBT actúa al escribir tests/código; este scope es solo docs+plan. Se incluye "adoptar PBT-partial" como ítem recomendado en el plan de remediación)
