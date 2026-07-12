# Reverse Engineering Metadata

**Analysis Date**: 2026-07-12T13:20:00Z (refresh cerrado — 8/8 artefactos + auditoría de consistencia)
**Refresh previo**: 2026-07-11T11:45:00Z (7/8 artefactos; code-quality-assessment quedó pendiente)
**Previous Analysis**: 2026-06-21T22:49:10Z (stale — describía modo console + flujo clásico, pre-Ciclo 4)
**Analyzer**: AI-DLC
**Workspace**: /home/renzo/.local/share/saga

## Motivo del refresh
Los artefactos originales (2026-06-21) describían la arquitectura VIEJA: modo `console` de LiveKit +
flujo clásico dual `VOICE_LIVEKIT`. Todo eso se ELIMINÓ en U7. Desde entonces el sistema cambió de raíz:
- **Ciclo 4** — migración console → room (U1-U6): server nativo + browser cliente + worker.
- **U7** — eliminación del transporte console y el flujo clásico standalone.
- **U8** — dispatch automático nativo (AgentServer load_fnc=0, @server.rtc_session sin agent_name).
- **U9** — cap de threads ONNX (CPU del wake).
- **U10** — turn detector semántico (MultilingualModel) → VAD puro Silero (−1.8 GB RAM).
- **U11** — toggle `VOICE_FULL_STACK` → `CLAUDE_PLUGINS` (stack agéntico opt-in) + blacklist.

## Artifacts Generated (refresh 2026-07-11)
- [x] business-overview.md — flujos actuales (room único)
- [x] architecture.md — topología room-only (server nativo ↔ browser ↔ worker)
- [x] code-structure.md — árbol real verificado (git ls-files); módulos clásicos marcados como eliminados
- [x] api-documentation.md — interfaces internas actuales (orb HTTP/SSE + LK_CTL_SOCK + CLAUDE_SOCK)
- [x] component-inventory.md — 4 procesos runtime + componentes lógicos actuales
- [x] technology-stack.md — LiveKit/Deepgram/VAD puro/CLAUDE_PLUGINS; deps verificadas vs pyproject.toml
- [x] dependencies.md — pip/vendored/nativo/servicios; sin pins inventados
- [x] code-quality-assessment.md — REFRESCADO 2026-07-12 (estado post-U7–U11: bug TTS agéntico, U7.3
  vestigial, wake shutdown/recall, deps muertas; ya no cita el flujo clásico ni helpers de TTS borrados)

## Auditoría de consistencia (2026-07-12)
Tras el refresh, se auditaron los 7 artefactos vs código real (HEAD 57399b3) y se corrigió el drift:
- api-documentation.md — sacada `is_goodbye` (removida) + sección `vc.tts` (helpers borrados en U7).
- component-inventory.md — WakeWordTrackDetector en `lk/wakeword.py` (no agent.py); `/events` SSE vs
  `/state` setter; `is_goodbye` fuera; `sound.py` VIVO (beep del wake); test_pure = 3 clases reales
  (sin TTS); `tools/say.py` → `measure_stack.py`.
- technology-stack.md — CI existe (`tests.yml`); wake corre en el worker (no server).
- business-overview.md — wake en el worker (no server).
- dependencies.md — `vc/app.py` es el entrypoint `saga` (press + doctor), NO un stub.
- architecture.md / code-structure.md — 100% consistentes, sin cambios.

## Fuentes autoritativas del refresh
`.claude/CLAUDE.md` (actual), `docs/` (architecture, code-guide, internal-api, operations, turn-flow),
`graphify-out/GRAPH_REPORT.md` (grafo reconstruido 2026-07-11), `pyproject.toml`, y el árbol real de código.
