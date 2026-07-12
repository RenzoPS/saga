# Ciclo 5 — saga agéntico (cargar plugins en Claude) — Requirements Questions

Contestá cada pregunta poniendo la letra después de `[Answer]:`. Si ninguna opción
encaja, elegí la última (Other) y describí abajo. Avisame cuando termines.

---

## Contexto y reality-check (leer antes de responder)

Objetivo declarado: **probar cómo reacciona el sistema al cargar plugins en el Claude
del voice** (hoy el daemon arranca _stripped_ con `--setting-sources ""` +
`--disable-slash-commands` → sin MCPs/skills/hooks/slash-commands; solo claude-mem opt-in).
El cambio de código es chico: togglear/sacar esa flag.

**Ojo con la hipótesis "U9 ya lo resuelve":** U9 capeó la CPU del **worker** (wake word
ONNX spinning, 410%→40%). El boot storm que abortó el spike previo venía de cargar los
**MCPs pesados del stack de Claude** (`config.py:37`: playwright lanza un Chromium, npx
baja paquetes, Google MCPs timeoutean) — y eso lo carga el **claude_daemon**, otro
proceso. Son cargas **ortogonales**: U9 liberó CPU del worker, pero el costo de levantar
los MCPs sigue ahí. Por eso este ciclo **mide** antes de dar por hecho que anda.

Además, cargar el stack tiene dos costos permanentes aunque no haya boot storm:

1. **Arranque del daemon** más lento (el strip bajó el primer token de ~57s a ~7s).
2. **Contexto por turno**: las tool-definitions de cada MCP entran en el prompt → más
   tokens/latencia en CADA turno de voz.

---

## Question 1

¿Cuál es el entregable del ciclo?

A) Spike de medición primero — cargar, medir la reacción (boot, latencia por turno, estabilidad del pipeline de voz) y RECIÉN AHÍ decidir si se queda. Entregable = medición + decisión go/no-go.

B) Implementar directo — cargar los plugins de forma permanente asumiendo que U9 alcanza, sin gate de medición previo.

X) Other (describir después de [Answer]:)

[Answer]: A

## Question 2

¿Qué se carga exactamente?

A) Full stack — sacar `--setting-sources ""` → carga user+project+local (TODOS los MCPs/skills/hooks). Máxima superficie y máximo riesgo de revivir el boot storm (playwright/Chromium, npx, Google MCPs).

B) Selectivo — cargar solo plugins livianos vía `--plugin-dir`/setting-sources curado, EXCLUYENDO a propósito los MCPs pesados que rompieron el spike (playwright, Google). Patrón que ya se usa hoy con claude-mem.

C) Lista exacta a definir — vos me decís qué plugins puntuales querés (nombrámelos) y armo la carga solo de esos.

X) Other (describir después de [Answer]:)

[Answer]: C, no tengo idea, la idea esque vos me ayudes con esto

## Question 3

¿Mecanismo del cambio?

A) Toggle reversible por env, default OFF (como el spike `VOICE_FULL_STACK` previo) — el arranque por defecto sigue stripped; los plugins se prenden a demanda para probar.

B) Permanente — cambiar el default del daemon a cargar plugins (sin toggle).

X) Other (describir después de [Answer]:)

[Answer]: A

## Question 4

¿Criterio de éxito / abort? (el norte del Ciclo 7 fue worker chico; cargar plugins infla)

A) Latencia por turno (TTFT) — gate duro: si el primer token no regresa a ~2-3s o el arranque del daemon se dispara, abortar.

B) Solo estabilidad — que NO se caiga el pipeline de voz (boot storm / inanición de CPU). Latencia extra se tolera.

C) Ambos — estabilidad del arranque + techo de latencia por turno.

X) Other (describir después de [Answer]:)

[Answer]: C

## Question 5

god-mode / seguridad. El daemon corre `--dangerously-skip-permissions`. Cargar MCPs con
efectos externos + voz = un mishear puede disparar acciones reales (mandar mail, abrir browser, etc.).

A) Mantener god-mode + el guard PreToolUse actual (solo bloquea Bash catastrófico). Aceptar el riesgo para el spike.

B) Endurecer — para plugins con efectos externos, sumar gating (permisos o allowlist de tools) antes de cargarlos.

X) Other (describir después de [Answer]:)

[Answer]: Ok, en cuanto a esta: yo tenia un pluging que bloqueaba acciones peligrosas pero lo saque. No tengo idea como era porque lo borre, me rompia los huevos, pero estaria interesante quizas descargarlo. Te invito a que busques en los documentos ~/Documents/setup-claude, o algo asi, hay muchos y en uno se tocaba el tema.

---

## Extensiones (opt-in del framework AI-DLC)

## Question: Security Extensions

Should security extension rules be enforced for this project?

A) Yes — enforce all SECURITY rules as blocking constraints (recommended for production-grade applications)

B) No — skip all SECURITY rules (suitable for PoCs, prototypes, and experimental projects)

X) Other (please describe after [Answer]: tag below)

[Answer]: B, demaciado exagerado, con un hook que te bloquee poder rompoer cosas y una regla dura en el prompt inicial estamos.

## Question: Resiliency Extensions

Should the resiliency baseline be applied to this project?

A) Yes — apply the resiliency baseline as directional best practices and design-time guidance.

B) No — skip the resiliency baseline (suitable for PoCs, prototypes, and experimental projects where rapid iteration matters more than reliability).

X) Other (please describe after [Answer]: tag below)

[Answer]: B, fuera de scope, no tratamos con cosas de aws

## Question: Property-Based Testing Extension

Should property-based testing (PBT) rules be enforced for this project?

A) Yes — enforce all PBT rules as blocking constraints.

B) Partial — enforce PBT rules only for pure functions and serialization round-trips.

C) No — skip all PBT rules (suitable for thin integration layers with no significant business logic).

X) Other (please describe after [Answer]: tag below)

[Answer]: C, es un simple prompt, el test lo mido yo y el timestamp del log
