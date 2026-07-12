# Story Generation Plan — Documentación de saga

Plan para convertir los requisitos (`requirements.md`) en historias de usuario centradas en los
**consumidores de la documentación**. Las historias servirán como criterios de aceptación de los
`docs/` (un doc "pasa" si cumple la historia). Respondé los `[Answer]:` y avisá cuando termines.

## Enfoque
Tratamos la documentación como un producto. "Usuario" = quien lee/usa la doc, no quien usa la voz.
Cada historia: **"Como <persona>, quiero <resultado de la doc>, para <valor>"** + criterios de aceptación.

## Plan de ejecución (checklist — Parte 2: Generación)
- [ ] Definir personas de consumidores de doc (`personas.md`)
- [ ] Escribir historias INVEST por persona (`stories.md`)
- [ ] Agregar criterios de aceptación testeables a cada historia
- [ ] Mapear cada persona → historias relevantes
- [ ] Mapear cada historia → archivo(s) de `docs/` que la satisface(n)

---

## Preguntas de planificación

## Question 1
¿Qué personas (arquetipos de lector) querés cubrir? (elegí una opción; multi-persona recomendado)

A) **Mantenedor nuevo** — dev que hereda el repo y tiene que entenderlo/extenderlo

B) **Operador / usuario diario** — corre saga día a día (start/stop/status, troubleshooting), no toca código

C) Mantenedor nuevo + Operador (las dos de arriba)

D) Mantenedor + Operador + **Debugger** (alguien cazando un bug en el flujo de voz/latencia) + **Contribuidor** (manda cambios, necesita convenciones del repo)

X) Other (please describe after [Answer]: tag below)

[Answer]: 

---

## Question 2
¿Cómo organizamos las historias (breakdown approach)?

A) **Persona-based** — agrupadas por tipo de lector (cada persona con sus historias)

B) **User journey-based** — siguiendo el recorrido del lector (instalar → primer turno → entender arquitectura → debuggear)

C) **Doc-section-based** — una historia por sección/archivo de `docs/`

X) Other (please describe after [Answer]: tag below)

[Answer]: 

---

## Question 3
¿Qué granularidad y volumen de historias preferís?

A) **Pocas y gruesas** — ~4-6 historias épicas, una por gran necesidad (más rápido, menos detalle)

B) **Balanceado** — ~8-12 historias medianas con criterios concretos (recomendado)

C) **Muchas y finas** — historias chicas y numerosas con sub-tareas (máximo detalle, más overhead)

X) Other (please describe after [Answer]: tag below)

[Answer]: 

---

## Question 4
¿Formato de los criterios de aceptación?

A) **Checklist** — lista de verificaciones concretas por historia (simple, fácil de chequear)

B) **Given/When/Then** (Gherkin) — escenarios estructurados (más formal)

C) **Híbrido** — Given/When/Then para los flujos clave, checklist para el resto

X) Other (please describe after [Answer]: tag below)

[Answer]: 

---

## Question 5
La definición de "valor" de cada historia, ¿la anclamos a una métrica/criterio observable?

A) Sí — cada historia define un resultado medible (ej: "un dev nuevo corre saga sin ayuda en <30 min")

B) No hace falta — alcanza con criterios de aceptación cualitativos (checklist de contenido presente)

X) Other (please describe after [Answer]: tag below)

[Answer]: 
