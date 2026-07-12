# Wake word "hey saga" — Requirements (decisiones) — CERRADO 2026-06-22

> Estado: **COMPLETO**. Todas las decisiones tomadas. Archivo de referencia histórica.

## Decisiones del sistema (pre-research)
- **Engine wake** = **livekit-wakeword** (oficial LiveKit, ~0.08 falsos+/h, ONNX, nativo a saga).
- **Integración** = dentro del agente LiveKit (dispara el flujo `press` interno).
- **Scope hardware** = corre donde sea (CPU ok), NO optimizar para Pi por ahora.
- **NFR duro** = nada regresa la velocidad Deepgram+Claude; wake+verify corren fuera del response
  path; gate de aceptación = benchmark de latencia en vivo.

---

## Decisiones de este ciclo (Ciclo 2 — solo wake word)

### Q2: Mic always-on
**[Answer]: B** — Toggle/opt-in. Wake apagado por default; Win+Z sigue siendo el activador
primario. El mic-always-on es opt-in cuando el usuario lo enciende explícitamente.

### Q3: Entrenamiento del wake (acento)
**[Answer]: A** — Synthetic-only. Generar samples con TTS (voces sintéticas ES), sin grabar nada.
Fine-tune manual solo si los falsos positivos/negativos son inaceptables en prueba real.

### Q4: Frase
**[Answer]: A** — "hey saga". Prefijo + dos sílabas = menor tasa de falsos positivos.

---

## Decisiones diferidas (Ciclo 3 — speaker verification)

### Q5: Scope del speaker verification
**[Answer]: B** — Wake ahora, speaker después. Este ciclo entrega "hey saga" funcionando.
La capa biométrica "solo mi voz" va en el próximo ciclo.

### Q1: Tier de speaker verification (Ciclo 3)
**Decisión pendiente para Ciclo 3.** Opciones: A) ECAPA-TDNN (recomendado), B) 3D-Speaker,
C) NeMo TitaNet. No bloquea este ciclo.
