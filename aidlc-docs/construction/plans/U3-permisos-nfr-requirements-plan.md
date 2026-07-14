# Plan — NFR Requirements: U3 (Modelo de permisos)

**Stage**: CONSTRUCTION → NFR Requirements (obligatorio por **PBT-09**)
**Unidad**: U3 — Modelo de permisos · **Rama**: `feature/ciclo9-u3-permisos`
**Entrada**: Functional Design de U3 (7 propiedades U3-P1…U3-P7) + NFR1…NFR5 del Inception

---

## 1. Pasos

- [x] **Paso 1 — Analizar el Functional Design** (las 4 capas, las 7 propiedades, los 5 riesgos R1-R5)
- [x] **Paso 2 — PBT-09: selección de framework** (¿hace falta una herramienta nueva?)
- [x] **Paso 3 — Definir el método de medición del gate G1** (latencia: A/B contra el baseline)
- [x] **Paso 4 — Evaluar cada NFR del ciclo contra esta unidad** (NFR1…NFR5)
- [x] **Paso 5 — Preguntas al usuario** (§2)
- [x] **Paso 6 — Generar artefactos** (`nfr-requirements.md` + `tech-stack-decisions.md`)
- [x] **Paso 7 — Compliance de extensiones** y mensaje de completitud

---

## 2. Preguntas

### Q1 — ¿Cómo se mide el gate G1 (latencia no detectable)?

NFR1 es el gate más duro del ciclo y es el que puede tumbar a U3. El baseline que dejó U1 es **histórico y
sucio**: mediana **~2.09s** de TTFT sobre 120 turnos del `saga.log`, en modo rápido (`CLAUDE_PLUGINS=0`). El
propio artefacto de U1 lo advierte: *"baseline LIMPIO pendiente de captura controlada"*.

- **A) A/B controlado en la misma sesión** (recomendado): antes de mergear, se corren **N turnos idénticos**
  con god-mode (rama `main`) y **N turnos idénticos** con `auto` (rama de U3), misma máquina, misma sesión,
  mismo prompt. Se compara la **mediana del TTFT**. Es el único número honesto: elimina el ruido del histórico.
- **B) Contra el histórico**: comparar los turnos nuevos contra la mediana ~2.09s del `saga.log`. Barato, pero
  compara peras con manzanas (el histórico mezcla condiciones de red y de carga distintas).
- **C) Solo validación perceptual**: el usuario dice si "se siente igual". Es el criterio **final** de NFR1
  ("latencia NO DETECTABLE"), pero sin número no hay evidencia si mañana alguien pregunta.

**[Answer]**: **A + C** (asunción del AI, delegada y reportada). El número (A) es la evidencia; la percepción (C)
es el criterio de aceptación real, porque NFR1 se define como *"no detectable"*, no como *"menos de X ms"*. Si
divergen (el número sube pero no se siente), **manda la percepción del usuario** — y se registra la divergencia.

---

### Q2 — ¿Hace falta una herramienta nueva? (PBT-09)

**[Answer]**: **NO.** Hypothesis ya está adoptado y configurado desde U1 (con sus 4 requisitos verificados:
generadores custom, shrinking, seed, integración con pytest). U3 **hereda** el stack tal cual: pytest · Hypothesis
· ruff · mypy · pip-audit. **Cero dependencias nuevas** — el parser del guard usa `shlex` (stdlib).
Se agrega un perfil de ejecución, no una herramienta: las propiedades de seguridad de U3 (U3-P1, U3-P3, U3-P5,
U3-P6) entran al perfil **thorough** (1000+ ejemplos), igual que las de U1/U2.

---

### Q3 — ¿Qué pasa si el guard nuevo (parser) resulta más lento que el regex?

El guard corre como **hook `PreToolUse`, en un proceso `python3` nuevo, en cada tool call de Bash**. Hoy hace
~15 `re.search`. Mañana hace `shlex.split` + normalización + reglas.

**[Answer]**: **No es un riesgo real, y se verifica igual.** El costo dominante del hook es el **arranque del
intérprete** (~20-30ms), no el matching (microsegundos). `shlex.split` sobre una línea de comando es
irrelevante frente a eso. Se mide igual en Build & Test (benchmark del hook aislado) y se registra el número —
si por algún motivo el parser costara más de ~5ms, se revisa. **Requisito**: el guard debe resolver en **< 50ms**
(techo generoso: es imperceptible dentro de un turno de voz de ~2s).
