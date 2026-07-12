# Ciclo 3 — Fix buffer de audio + feedback "no hay voz" — Requirements (decisiones)

> Estado: **COMPLETO** (decisiones tomadas 2026-06-23). Avanza a Workflow Planning.

## Intent Analysis
- **User request**: el wake (y Win+Z) dejan el orbe pegado en "Grabando" cuando no hay voz;
  el turno no cierra. Resolver SIN tocar buffers/streaming a mano (solo herramientas nativas
  de LiveKit). Recuperar el feedback visual del modo viejo (amarillo "No te entendí").
- **Request type**: Bug Fix + Enhancement (UX feedback).
- **Scope**: Single Component (`lk/agent.py`, flujo de audio del agente LiveKit).
- **Complexity**: Moderate (API de LiveKit; el buffer de `rtc.AudioStream` es opaco).

## Causa raíz (research, Build&Test Ciclo 2)
En modo console, `session.input.set_audio_enabled(False)` NO detiene la captura física: el
`rtc.AudioStream` (livekit-core, C++) sigue acumulando audio durante el idle. Al reabrir el mic,
LiveKit entrega TODO el backlog (medido: 121s tras 123s en idle) → el VAD/turn-detection/away se
ahogan procesando audio viejo → el turno no cierra → orbe pegado en "Grabando".

## Decisiones del ciclo

### Q1: Mecanismo nativo del fix
**[Answer]: clear_user_turn** (el usuario lo dejó a criterio del implementador).
- `pause()`/`resume()` DESCARTADO: el código fuente de livekit-agents dice explícito
  *"must only be called by AgentSession"* — son métodos internos de transición de agente
  (cierran/reinician la sesión, drenan tasks, manejan `_ReusableResources`). Usarlos a mano
  sería frágil/frankenstein → viola la restricción del usuario.
- **Elegido**: `session.clear_user_turn()` al ENTRAR en rec (recrea el pipeline STT, descarta el
  turno con backlog). Nativo, mínimo. Garantía empírica (el buffer core es opaco) → se valida en
  Build&Test; si persiste, se escala (ej. descartar el primer chunk al abrir).

### Q2: Feedback visual "no hay voz"
**[Answer]: SÍ** — recuperar el estado `error` amarillo ("No te entendí") del modo viejo.
Cuando el `user_away_timeout` dispara (no hablaste) o el turno sale vacío → `orb_state("error")`
(amarillo, ya existe en `orb/orb.html`) en vez de `cancel`. Transitorio → vuelve a idle.

### Q3: Scope — reactivar wake en este ciclo
**[Answer]: SÍ** — al cerrar el fix, reactivar `SAGA_WAKE_ENABLED=1` y validar en vivo que el wake
ya no cuelga el orbe. Cierra el loop pendiente del Ciclo 2.

## NFR
- **Restricción dura (usuario)**: NO manipular buffers/streaming a mano. Solo API/config nativa de
  LiveKit.
- No regresar la latencia Deepgram+Claude (NFR vigente de ciclos previos).

## Extensiones
Todas opt-out (Security / Resiliency / PBT = No, heredado de Ciclo 1). Sin gate bloqueante.
