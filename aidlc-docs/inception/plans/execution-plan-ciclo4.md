# Execution Plan — Ciclo 4: Migración modo console → modo room (LiveKit)

**Generado**: 2026-06-23
**Tipo**: Migration / Refactoring — Brownfield
**Alcance**: Transporte de audio (console → room). El cerebro IA (STT/LLM/TTS/VAD/wake) se conserva.
**ESTE CICLO**: SOLO planificación/documentación (Inception). Construction (código) = ciclo futuro, tras
aprobación explícita.

---

## Detailed Analysis Summary

### Transformation Scope
- **Cambia**: entrypoint del agente (`console` → `start`), `saga-ctl` (gestiona livekit-server), cliente
  publicador del mic (NUEVO, browser del orbe), orbe (pasa a participante WebRTC), config (keys locales).
- **Se conserva**: `lk/claude_llm.py`, `vc/` entero, modelo wake, plugins (Deepgram/Silero/BVC), system prompt.

### Change Impact Assessment
- **Buffer**: resuelto (room descarta frames con mic apagado — `room_io/_input.py:154-156`).
- **Orbe**: gana sincronización con la voz real (recibe el track TTS del room).
- **Multi-dispositivo**: habilitado (cualquier cliente se conecta al room).
- **Latencia**: WebRTC local ~ms; NFR a confirmar con benchmark.

### Risk Assessment
Ver `room-migration-requirement-questions.md` (sección Riesgos). Top 3:
1. Cliente publicador del mic (browser) = el grueso del trabajo nuevo.
2. Dónde corre el wake (browser vs agente-sobre-track) — a resolver en Application Design.
3. saga-ctl orquesta más procesos (server + worker).

---

## Phases to Execute

### INCEPTION PHASE (Ciclo 4) — ESTE CICLO
- [x] Workspace Detection — reutilizado de Ciclo 1
- [x] Reverse Engineering — reutilizado de Ciclo 1 (brownfield vigente)
- [x] Requirements Analysis — COMPLETO (room-migration-requirement-questions.md; AI respondió, usuario delegó)
- [ ] User Stories — SKIP (refactor de infra; sin nuevas historias de usuario más allá de "el wake anda")
- [ ] Workflow Planning — **EN CURSO** (este documento)
- [ ] **Application Design — EXECUTE** (NO skip: hay transporte/componentes nuevos — server, cliente
      publicador, orbe-participante; diseñar la topología y dónde corre el wake). Es documentación, no código.
- [ ] Units Generation — posible (descomponer: server infra / worker / cliente-mic / orbe-participante).

### CONSTRUCTION PHASE (Ciclo 4) — NO EN ESTE CICLO
- [ ] Functional/NFR/Infra Design — futuro
- [ ] Code Generation — **FUTURO** (requiere aprobación explícita; NO se hace ahora por pedido del usuario)
- [ ] Build and Test — futuro (incluye benchmark de latencia = NFR gate)

### OPERATIONS PHASE
- [ ] Operations — futuro (saga-ctl orquestando server + worker; readiness).

---

## Application Design — temas a documentar (próximo paso de ESTE ciclo)
1. **Topología room**: livekit-server (Docker) ↔ worker (agente) ↔ cliente-browser (mic + orbe + TTS).
2. **Flujo de audio**: browser captura mic → publica track al room → worker (agente) lo recibe → STT/LLM/TTS
   → worker publica respuesta → browser la reproduce + anima el orbe sincronizado.
3. **Dónde corre el wake**: decisión (browser onnxruntime-web vs agente sobre el track del room) + trade-offs.
4. **Win+Z**: cómo se adapta el socket de control al nuevo flujo.
5. **saga-ctl**: nuevos procesos/readiness (server up, worker conectado, browser).
6. **Config/keys**: generación local de LIVEKIT_URL/API_KEY/API_SECRET (sin cloud).
7. **Fallback console**: cómo coexisten room (default) y console (dev) sin romper.

---

## Success Criteria (del ciclo de Construction futuro, documentados acá)
- Wake usable: sin backlog, sin respuestas fantasma, el orbe no se cuelga.
- Orbe sincronizado con la voz real.
- Latencia ≤ actual (~2-3s) — benchmark gate.
- Win+Z y fallback console siguen andando.
- Todo local (sin cloud).

---

## Nota de numeración de ciclos
- Ciclo 1: documentación ✅ · Ciclo 2: wake word ✅ · Ciclo 3: fix buffer (diagnóstico, revertido) ✅
- **Ciclo 4: migración a room (este)** · Ciclo 5: speaker verification (diferido, "solo mi voz").
