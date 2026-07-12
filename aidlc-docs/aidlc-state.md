# AI-DLC State Tracking

## Project Information
- **Project Type**: Brownfield
- **Project Name**: saga
- **Start Date**: 2026-06-21T22:49:10Z
- **Current Phase**: **Ciclo 8 — Limpieza de deuda técnica (INCEPTION).** Doc-sync 2026-07-12 CERRADO y
  en main (commits 342fb2b docs + f269a5d framework). Ciclos 4/5/7 CERRADOS y en main.
- **Current Stage**: Ciclo 8 CONSTRUCTION CERRADA (código + Build&Test estático verde) en rama
  `feat/ciclo8-cleanup-deuda`. Q1=A/Q2=A (delegado al AI). **Pendiente: commit/push (OK del usuario).**
  Pendientes previos sin cambio: meditar qué plugins útiles; bug TTS agéntico abierto (fuera de scope).
- **Última actualización de docs del repo**: U11 (commit 57399b3) sincronizó `docs/` + README. El toggle hoy es
  `CLAUDE_PLUGINS` (antes `VOICE_FULL_STACK`, renombrado en U11).

## Mapa de ciclos
- **Ciclo 1**: documentación del proyecto ✅
- **Ciclo 2**: wake word "hey saga" (modelo FPPH=0, commit 4743056) ✅
- **Ciclo 3**: fix buffer en modo console → cerrado como diagnóstico (no hay fix nativo en console; revertido) ✅
- **Ciclo 4**: migración console → room (transporte LiveKit). **✅ CERRADO Y MERGEADO** (PR #1 + PR #2).
  Unidades **U1–U8**: U1–U3 (infra/worker/cliente) + U5 (orbe sync) + U6 (saga-ctl) + U7/U7.1/U7.2 (cleanup
  room único) + **U8 (dispatch automático nativo, hardening del arranque)**. U4 (wake cliente) diferido.
  Server NATIVO (no Docker). Todo validado en vivo (cold boot del SO incluido).
- **Ciclo 5**: **saga AGÉNTICO** (tools/MCPs: hora, clima, Spotify). **⛔ SPIKE ABORTADO (2026-06-24)** — el
  spike `VOICE_FULL_STACK` mostró boot storm (load ~10, pipeline de voz caído por inanición de CPU) + ROI
  dudoso (saga ya es agéntica con bash/webfetch). Revertido. Diferido sin fecha. NO confundir con U9 (el
  commit de U9 quedó mal rotulado `ciclo5` por inercia de numeración — U9 NO es agéntico, es del Ciclo 7).
- **Ciclo 6**: speaker verification "solo mi voz". DIFERIDO desde Ciclo 2. NO arrancado.
- **Ciclo 7 (NUEVO) — Optimización de recursos del worker**: bajar CPU/RAM del worker de voz para hardware
  chico (Pi/mini-PC). Misma superficie (worker), mismo norte. Unidades:
  - **U9 — cap threads ONNX (CPU)**: ✅ CERRADO Y MERGEADO (PR #3). CPU worker 410%→40% (10x), sin perder
    detección. (Commit rotulado `ciclo5` por error histórico; pertenece acá.)
  - **U10 — RAM del turn detector**: ✅ CERRADO Y VALIDADO EN VIVO. `turn_detection` MultilingualModel
    (semántico, ~1.8 GB) → `"vad"` (VAD puro silero, ya cargado) + `min_delay` 2.0→3.0. RAM worker
    **2611 MB → 913 MB (−1.7 GB)**, UX igual (usuario: "se siente igual"). Bonus: se fue el "Error
    predicting end of turn". El turn detector era el 78% de la RAM (único consumidor grande).
  > **Ciclo 7 cerrado por ahora** (U9 CPU + U10 RAM). Worker pasó de ~410%/2.6 GB a ~40%/0.9 GB.
  > Próximo salto de hardware chico: split Pi (browser/mic vs worker) + onnxruntime-web para el wake (futuro).
- **Ciclo 8 (NUEVO) — Limpieza de deuda técnica**: cleanup brownfield, sin lógica nueva, sin tocar el flujo
  de voz. CORE: FR1 (cadena muerta cancel SIGUSR2 en vc/runtime.py + no-ops en claudecli) + FR2 (deps muertas
  turn-detector/noise-cancellation en pyproject). Optativos a decidir: wake shutdown, pin LiveKit, lint/CI.
  Requirements: inception/requirements/ciclo8-cleanup-requirements.md.

### INCEPTION Ciclo 8
- [x] Workspace Detection — RESUME (brownfield)
- [x] Reverse Engineering — SKIP (refresh 2026-07-12 vigente)
- [x] Requirements Analysis — COMPLETO (ciclo8-cleanup-requirements.md; Q1=A CORE, Q2=A solo pyproject, delegado al AI)
- [x] User Stories — SKIP (cleanup interno, cero impacto al usuario)
- [x] Workflow Planning — COMPLETO (execution-plan-ciclo8.md)
- [x] Application Design / Units Generation — SKIP (sin componentes/descomposición)

### CONSTRUCTION Ciclo 8
- [x] Functional / NFR Req / NFR Design / Infra Design — SKIP (sin lógica/modelos/infra nuevos)
- [x] Code Generation — Part 1 (ciclo8-cleanup-code-generation-plan.md) + Part 2 (código) HECHOS.
  3 archivos: vc/runtime.py (rewrite, saca cadena muerta), vc/claudecli.py (no-ops + de-indent),
  pyproject.toml (2 deps muertas). Summary: construction/ciclo8-cleanup/code/generation-summary.md.
- [x] Build & Test — CERRADO OK (estático). py_compile + tests 11/11 + import smoke + refs=0 + _cancel vivo.
  Detalle: construction/build-and-test/ciclo8-build-and-test.md. **Pendiente: commit/push (OK del usuario).**

## Ciclo 4 — Migración modo console → modo room (LiveKit)
- **Tipo**: migration/refactor del TRANSPORTE de audio. El cerebro IA (STT/LLM/TTS/VAD/wake) se conserva.
- **Por qué**: el modo console acumula audio (buffer, Ciclo 3); el modo room descarta frames con mic
  apagado (verificado en `room_io/_input.py:154-156`). Bonus: orbe sincronizado con la voz real + multi-device.
- **Decisiones** (2026-06-23, AI respondió por delegación del usuario — ver room-migration-requirement-questions.md):
  - Servidor: Docker self-hosted LOCAL (gratis, privado, sin cloud).
  - Cliente publicador del mic: el BROWSER del orbe (unifica mic+orbe+voz, da orbe sync gratis).
  - Wake: dónde corre = a definir en Application Design.
  - Win+Z y fallback console: se conservan.
  - Scope: transporte + orbe sync. NO speaker verification (Ciclo 5).
- **NFR duro**: no regresar la latencia ~2-3s (benchmark gate en Construction). Privacidad: audio local-only.

### INCEPTION Ciclo 4
- [x] Workspace Detection / Reverse Engineering — reutilizados
- [x] Requirements Analysis — COMPLETO (room-migration-requirement-questions.md)
- [ ] User Stories — SKIP (refactor de infra)
- [x] Workflow Planning — execution-plan-ciclo4.md
- [x] **Application Design — COMPLETO** (aidlc-docs/inception/application-design/). Topología room + flujo +
  **wake en el CLIENTE** (corregido tras revisar el vault: es el patrón estándar LiveKit + alineado con la
  visión "DesktopLayer como producto" + privacidad + cross-platform). Solo docs.
- [x] **Units Generation — COMPLETO** (6 unidades: U1 infra · U2 worker · U3 cliente audio · U4 wake cliente
  · U5 orbe sync · U6 saga-ctl). Ver unit-of-work.md + unit-of-work-dependency.md. Orden: U1 → U2+U3 → U4+U5 → U6.

> **INCEPTION Ciclo 4 CERRADA.** Toda la planificación/documentación lista. CONSTRUCTION (código) NO se hizo
> (pedido del usuario). Revisión con mente fría hecha: plan APROBADO + 1 cambio (wake worker→cliente) +
> consideraciones del vault (room agrega fricción al instalable; oportunidad de limpiar deuda D1).

### CONSTRUCTION Ciclo 4 — ACTIVA (2026-06-23, usuario aprobó cruzar el gate)
Per-Unit Loop. Orden: U1 → U2+U3 → U4+U5 → U6. Build&Test al final (incluye benchmark de latencia = NFR gate).

**U1 — Infra room** (en curso):
- [x] Functional Design — SKIP (sin modelos/lógica de negocio; infra + minteo JWT)
- [x] NFR Requirements / NFR Design — SKIP (extensiones opt-out; seguridad = constraint duro en el plan)
- [x] Infrastructure Design — SKIP (topología/readiness ya mapeada en Application Design; plegado al code-gen plan)
- [x] Code Generation — **Part 1 (plan) + Part 2 (código) HECHOS**. **PIVOT Docker→BINARIO NATIVO** (ver
  Build&Test abajo): el server corre como `~/.local/bin/livekit-server` (v1.13.1, tarball oficial, checksum
  verificado), NO Docker. `docker-compose.yml` ELIMINADO (muerto). `livekit.yaml` (server config: signaling
  loopback, udp_port 7882 único, node_ip por env NODE_IP), vc/config.py (carga .env.local + constantes
  LIVEKIT_*), orb/orb_server.py (GET /token mint JWT lazy), .env.local (keys generadas). Verif: py_compile OK,
  JWT round-trip OK, server nativo HTTP 200, auth API OK, /token end-to-end OK. Summary: construction/U1-infra-room/code/.
- [x] **U2 (worker modo room) — HECHO**. `lk/agent.py`: detección de modo (`console` en argv), wake
  server-side gateado a console (en room va al cliente U4), log de transporte, docstring. Conserva todo el
  cerebro IA + Win+Z + claude_llm. Verif: py_compile OK + `lk/agent.py start` registra worker contra
  ws://127.0.0.1:7880 y espera dispatch. Summary: construction/U2-worker-room/code/.
- [x] **U3 (cliente browser audio) — HECHO**. `orb.html`: SDK livekit-client 2.19.2 vendoreado
  (orb/vendor/livekit/), conexión al room por /token, mic publicado muteado con gate por estado SSE
  (rec→unmute), reproducción del TTS + unlock autoplay, CustomEvent('orbstate'). BUG cazado+arreglado:
  orb_server MIME `.mjs`. Summary: construction/U3-cliente-audio/code/.

#### Build & Test PARCIAL (integración en vivo U1+U2+U3) — 2026-06-23 ✅ ANDANDO
Validado en el browser REAL del usuario: **turno de voz completo (texto Shift+Enter Y voz Win+Z) responde por
voz**. Worker llega a `agent_state -> speaking`, LLM + TTS completos, ICE conecta por UDP. Esto resuelve de
fondo el bug del buffer del Ciclo 3 (room descarta frames con track detached).

**PIVOT crítico — Docker → binario nativo (causa raíz: Docker NAT rompe WebRTC local):**
- Síntoma: orbe clavado en "Pensando"; en logs `dtls timeout` + el job salía a los ~30s. El cerebro+TTS
  funcionaban (LLM respondía, TTS generaba audio) pero el MEDIA no se entregaba.
- Diagnóstico (server logs): el transporte WebRTC del worker/cliente daba `dtls timeout`. Probado en host-net
  (UDP bindeaba a interfaz equivocada) y bridge+publish (NAT de Docker rompe el handshake DTLS). Causa = Docker
  NAT sobre WebRTC en localhost.
- Fix: **sacar Docker.** `livekit-server` como binario nativo (tarball oficial v1.13.1, checksum SHA256 OK,
  en `~/.local/bin/`, fuera del repo). Config: signaling loopback (default LiveKit), `udp_port` único 7882,
  `node_ip` = IP LAN auto-detectada por env `NODE_IP` (LiveKit no bindea UDP a loopback nunca → el candidato
  debe ser la interfaz real; signaling sigue loopback → nadie externo se une). Resultado: ICE por UDP, 0 dtls
  timeout, voz andando.
- **Auditoría contra doc oficial (context7)**: server/worker/token/cliente usan las herramientas de LiveKit
  como mandan (AccessToken+VideoGrants verbatim, agent.py start, livekit-client SDK, config nativa). Pivot a
  nativo = recomendación oficial para local. No es frankenstein.

**Fixes aplicados en esta integración (commiteados):**
- `lk/agent.py`: BVC noise_cancellation gateado a console (BVC requiere LiveKit Cloud; en self-hosted tiraba
  error). Alternativa self-host = ai_coustics (anotada, no aplicada).
- `lk/agent.py`: migrado `RoomInputOptions` (deprecado) → `RoomOptions(audio_input=AudioInputOptions(...))` (API 1.6).
- `orb/orb_server.py`: MIME `.mjs` (el SDK ESM se servía como octet-stream).

**Deuda anotada (pulido, no blocker):** (1) volumen de la respuesta baja en call de voz = echo-cancellation
ducking del browser (ajustable); (2) el path de Win+Z (socket Unix + SSE) es glue propio, no primitiva LiveKit
(revisable con data channel/RPC o full client-side en U4); (3) evaluar ai_coustics si molesta el ruido.

- [x] **U6 (saga-ctl modo room) — HECHO** (start en vivo pendiente de usuario). REORDENADO antes de U4/U5
  (U4 = port más caro/riesgoso; el sistema ya anda con Win+Z). `vcctl.py` + `vc/config.py`: `_start_room()`
  (server nativo NODE_IP-auto + claude + orb + worker start + xdg-open), `_livekit_server_pids()` (stop baja
  el binario), `SAGA_TRANSPORT=room|console`. Verif: py_compile OK; `saga-ctl status/stop` OK (stop baja el
  binario sin tocar este claude); `start` lo confirma el usuario en vivo. Summary: construction/U6-saga-ctl/code/.
#### Build & Test — hallazgos en vivo (2026-06-23)
- **Dispatch RESUELTO** (commit 9ccd758): dispatch explícito por API (agent_name + saga-ctl crea el dispatch).
- **Voz end-to-end andando**, MUY rápida (chunks parciales al LLM). Texto Shift+Enter limpio.
- **Logging de eventos en el monitor** (pedido del usuario) — HECHO: `_event()` en lk/agent.py con prefijo `▎`
  para Win+Z (grabar/cortar/cancelar), SILENCIO detectado, PENSANDO/HABLANDO, listo, texto. Confirmado: anda.
- **RESUELTO — turnos perdidos + chopping + away a los 0s** (verificado en vivo: "todo funciona, no falló en
  ningún momento"). 3 fixes en lk/agent.py:
  - `preemptive_generation=False`: la preemptive gen de LiveKit arrancaba el LLM sobre transcripts parciales y
    lo cancelaba/reintentaba; con el LLM custom (bridge bloqueante) eso colgaba el turno (`claude prompt` sin
    `turn OK`). Flag OFICIAL de AgentSession.
  - `endpointing min_delay 2→3s` (max 4→5): menos chopping (frases con pausas no se parten). Config oficial.
  - away timer: el away disparaba "no entendí" a los 0s (timer stale del idle anterior). **DEUDA SALDADA**
    (2026-06-23): reemplazado `user_away_timeout` nativo + `session._set_user_away_timer()` (privado) por un
    timer PROPIO `asyncio.call_later`, VAD-aware (arma en Win+Z, cancela al `speaking`/`thinking`). Sin
    internals de LiveKit. Verificado en vivo (usuario: 3 casos OK). + el timeout pinta el orbe AMARILLO
    "No te entendí" (estado `error`), no el rojo `cancel`.
  - Commits: ver git (turn-handling fixes).
- **DESCUBRIMIENTO (→ Ciclo 5 agéntico)**: saga no hace acciones (hora/clima/Spotify) porque corre con
  `--setting-sources ''` (sin MCPs/tools) + prompt que desalienta tools. No es bug de Ciclo 4. Ver Ciclo 5.

- [x] **U5 (orbe sync) — HECHO** (verificado en vivo, usuario 10/10). `orb.html`: el browser mide el nivel
  REAL del track TTS (Web Audio AnalyserNode) → el orbe late con la voz (lo desbloqueó el modo room; en console
  era imposible). Suavizado de envolvente (ataque/release asimétrico) + techo de escala (no se infla) +
  desbloqueo de autoplay sin botón (gesto). Fallback sintético: nunca queda plano. Commit ed7620c.
  Artefactos AI-DLC: plans/U5-orbe-sync-code-generation-plan.md + U5-orbe-sync/code/generation-summary.md.
  Build&Test del ciclo: build-and-test/ciclo4-build-and-test.md (11 issues encontrados+resueltos, tabla).

#### Build & Test — robustez del turno de voz (2026-06-23, verificado 10/10)
- **CAUSA RAÍZ del chopping/no-respuesta**: `preemptive_generation` quedaba ON. El param top-level está
  DEPRECADO y se ignora cuando se pasa `turn_handling`; el default es `enabled: True` (verificado en el source
  livekit `turn.py:151`). Fix: ponerlo DENTRO de `turn_handling={"preemptive_generation":{"enabled":False}}`.
  Esto mata el multi-commit (LLM sobre transcripts parciales) que partía/cancelaba turnos.
- **Turn detector semántico** (`MultilingualModel`, español) en `turn_handling` + `min_delay 2.0`: anti-chopping.
- **Cancel mata el turno del daemon** (`claude_daemon.py`): al cancelar, mata el grupo entero (sin zombie/
  huérfano) y respawnea con `--resume` (contexto intacto). Antes drenaba → daemon ocupado.
- **Watchdog** (`_busy`, 18s) + **empty-cut** (rapid Win+Z sin hablar → amarillo al toque): destraban cuelgues.
- Lección: NO adivinar config de LiveKit — verificar campos contra el TypedDict + el source. Hubo churn por eso.

- [x] **Build & Test final — CERRADO**: benchmark de latencia (NFR gate) corrido y registrado
  (build-and-test/ciclo4-build-and-test.md): cerebro 2.2s + voz 0.3s ≈ 2.5s, NO regresó (la percibida ~4.5s
  incluye el min_delay 2.0 anti-chopping, decisión tuneable). NFR ✅.
- [x] **README / docs — ACTUALIZADOS** a modo room (default): `.claude/CLAUDE.md` (arquitectura room + gotchas
  room + obsoletos corregidos), `README.md`, `lk/README.md`, y `docs/` completo (architecture, turn-flow,
  operations, internal-api, code-guide, tech-debt-plan, README). Verificados contra código (agentes en paralelo).
- [x] **U4 (wake "hey saga") server-side — CÓDIGO GENERADO** (2026-06-23, en vivo PENDIENTE). REDEFINIDA: en
  el SERVER (sobre el track), NO en el cliente. Decisión del usuario: server-on-track reusando el wake Python
  (livekit.wakeword) en vez del port a onnxruntime-web (evita el frankenstein). Part 1 (plan) aprobado + Part 2
  (código) hecho. 4 archivos: `lk/wakeword.py` (+`WakeWordTrackDetector`: rtc.AudioStream del track → ventana 2s
  deque → `predict` en executor cada ~240ms → debounce → `_press`); `lk/agent.py` (import rtc + track_subscribed
  /barrido del mic → arranca el detector en room; console sigue con el detector local); `orb/orb_server.py`
  (`/token` agrega flag `wake`); `orb/orb.html` (wake ON → mic DESMUTEADO siempre, gate orbstate off). Verif:
  py_compile OK + import smoke OK + predict smoke (chunking 2s→0.002, 80ms→0.0, CHUNK_FRAMES=25=2s) ✅. Opt-in
  `SAGA_WAKE_ENABLED=1`, default OFF. Summary: construction/U4-wake-server/code/generation-summary.md.
  **Pendiente: validación EN VIVO del usuario** ("hey saga" → graba). Riesgos abiertos:
  dos consumidores del track (plan B FrameProcessor) · falsos positivos · privacidad mic continuo (mitigado opt-in).
  Commit 2c4bae1 (U4 + fixes browser-dup/dispatch-503).
- [x] **U7 (cleanup: LiveKit/room estándar ÚNICO) — HECHO** (2026-06-23, commit 53d9960, en vivo PENDIENTE).
  Decisión INCEPTION del usuario: room es el estándar, no negociable. ELIMINADOS: (1) transporte console
  (`SAGA_TRANSPORT=console`, bug del buffer + glue `_CONSOLE_MODE`); (2) flujo clásico (`VOICE_LIVEKIT=0`,
  máquina de turnos standalone `vc/app.py` + STT/TTS propios). Único configurable que queda: wake on/off
  (`SAGA_WAKE_ENABLED`) + Deepgram-o-fallback (sin key → faster-whisper+edge DENTRO del agente). BORRADOS:
  vc/audio.py, vc/stt.py, vc/tts.py, whisper_daemon.py. Adelgazados: vc/app.py (→ press+doctor), lk/agent.py
  (sin console/BVC), vcctl.py (start→_start_room, status room-only), vc/config.py (sin flags+huérfanas).
  CONSERVADOS (no romper): vc/runtime.py (hub compartido), wake_daemon.py/Vosk (DORMIDO, fuera de scope),
  fallback whisper/edge del agente, doctor. Verif: py_compile + import smoke + grep refs=0 + saga-ctl status
  room-only + saga --doctor OK. Net ~1300 líneas menos. Plan/summary: construction/U7-remove-console/.
  Mapeo de deps con grep ANTES de borrar (hallazgo: vc/app.py:main ES el emisor de Win+Z → adelgazado, no borrado).

> **CICLO 4 — CERRADO en lo sustancial.** U1+U2+U3+U5+U6 + dispatch + voz robusta + U4 (wake server) + U7
> (room estándar único, basura legacy eliminada). Todo verificado estáticamente + lo previo en vivo (10/10).
> Pendiente: validación en vivo del usuario de U4 (hey saga) + U7 (saga-ctl restart room-único).

### U7.1 — Terminar la limpieza de U7 (ABIERTA, 2026-06-23)
- **Disparador**: el bug del mic se cerró como ENTORNO (Brave/getUserMedia), NO código (ver DIAGNOSTICO-mic.md).
  El working tree se había revertido a U4 sobre esa hipótesis falsa. El usuario pidió re-revisar U7 antes de
  restaurarlo: que quede TODO limpio (sin código/proceso fantasma, sin race, buenas prácticas, sin frankenstein).
- **Re-revisión (3 agentes paralelos sobre worktree 53d9960)**: **arquitectura U7 = LIMPIA** (anti-frankenstein:
  cero edición de libs, cero internals privados de LiveKit, cero orquestación casera de audio, turn config
  impecable vs livekit-agents 1.6.0; deuda `_set_user_away_timer` SALDADA). U7 NO se rehace. **Pero la limpieza
  quedó incompleta** → unidad U7.1.
- **Punch-list** (ver plan): ALTA = tests/test_pure rota (importa vc.tts borrado) · tools/say.py roto · race del
  dispatch (`LK_CTL_SOCK.exists()` + socket stage→`_sock_up` + cleanup en shutdown) · doble dispatch (fuente
  única). MEDIA = huérfanas (is_goodbye/GOODBYE_KEYWORDS, WORD_ALIASES_PATH, WAKE_MAX_IDLE_TURNS) · `_node_ip`
  loopback silencioso. BAJA = comentarios/docs/TMP_FILES console-clásico stale · podar Vosk de DAEMONS.
- **Criterio resuelto**: `sounddevice` SE QUEDA (wake_daemon dormido + doctor) · `saga.py` VIVO (emisor Win+Z) ·
  glue Win+Z→RPC = deuda opcional fuera de scope · `wake_daemon.py` = dormido intencional, solo se poda de DAEMONS.
- **Stages**: Requirements = la punch-list (aprobada: "CLEANUP COMPLETO"). User Stories/App Design/Units/Functional/
  NFR/Infra = SKIP (cleanup brownfield, sin lógica/componentes nuevos). Code Generation (plan + ejecución) +
  Build&Test = EXECUTE. Plan: construction/plans/U7.1-cleanup-code-generation-plan.md.
- **Estado**: Code Generation Part 2 EJECUTADO + Build&Test estático CERRADO. 18 archivos, +135/-290.
  py_compile OK · `tests.test_pure` 11/11 VERDE (antes rota) · import smoke OK · grep refs=0 · verificador
  adversarial 0 blockers (dispatch fuente-única confirmado seguro). **Deuda nueva flageada** (fuera de scope,
  pase aparte): cadena muerta del clásico en `vc/runtime.py` (PID/LOCK/signal_stop/signal_cancel, 0 callers).
  **Pendiente**: commit (OK del usuario) + validación en vivo (`saga-ctl restart` + Win+Z).
- **FIX cold-start (Build&Test en vivo, 2026-06-24)**: validando, salió el bug 503-on-cold-start (PRE-EXISTENTE,
  no de U7.1): el server da el puerto de signaling HOT antes que el subsistema de agent-dispatch; en frío el
  worker registra en esa ventana → server envenenado ("no response from servers") hasta reiniciar ("1ra en frío
  falla, 2da anda"). Fix: gate `_dispatch_subsystem_ready()` (list_dispatch con timeout 2s) en `_start_room`
  paso 3.5, ANTES de lanzar el worker. **Verificado por mí** (corrí stop+start en frío total ×2): dispatch al
  primer intento (antes 6 retries+503), agente en room, socket creado. Falta solo el turno de voz (usuario).
- **U7.1 CERRADA (2026-06-24)**: turno de voz validado en vivo por el usuario ("anduvo 100%"). Doc alineada
  (token-dispatch stale corregido en README/code-guide/internal-api + gotcha cold-start agregado a CLAUDE.md).
  Threshold wake 0.05→0.08 (.env.local, gitignored). Commit **cf726f7** (NO pusheado). Build&Test CERRADO.
  Deuda viva para próximos ciclos: (a) U7.2 cadena muerta clásico en vc/runtime.py; (b) fine-tune wake con
  voz real (Ciclo 2 diferido); (c) `Executor shutdown` en el wake detector al bajar (lifecycle, menor);
  (d) push de la rama + PR a main; (e) Ciclo 5 agéntico (tools/MCPs).

### U7.2 — Limpieza cadena muerta del flujo clásico en vc/runtime.py (2026-06-24)
- **Disparador**: el usuario pidió cerrar de verdad sin una línea fantasma. Root-cause check: cadena PID/lock/
  SIGUSR del flujo clásico standalone (que U7 eliminó) quedó en runtime.py con CERO llamadores.
- **Verificado cero-callers (no de memoria)**: `pid_alive`, `_proc_starttime`, `self_identity`, `read_pid_from`,
  `read_recorder_pid`, `read_owner_pid`, `signal_stop`, `signal_cancel` + `PID_FILE`/`LOCK_FILE`. Borrados.
  TMP_FILES de vcctl: sacados `saga.pid/lock/abort/wav` (temps clásicos nunca creados en room).
- **Scope acotado a propósito**: NO toqué `cancel_handler`/streamer/`set_current_proc` (también dead pero
  ACOPLADOS al `set_current_proc` que claudecli llama vivo + al `_cancel` vivo) → su limpieza necesita tocar
  el path de cancel de claudecli (no runtime-testeable desde acá). Queda flageado (eventual U7.3).
- **Verificado por mí**: py_compile + tests.test_pure 11/11 + import smoke (runtime/claudecli/app/agent/vcctl)
  + grep refs=0 + `os`/`signal` siguen vivos en runtime + **boot en vivo** (stop+start: claude HOT, dispatch
  del server HOT, agente en room, ambos sockets). El daemon (claudecli→runtime) sigue sano.
- **Estado**: CERRADO. Commits `86b3d9a` (U7.2) + `bc2cdb6` (CI) pusheados. **PR #1 mergeado a `main`**
  (merge `01b7161`). CI (`.github/workflows/tests.yml`: py_compile + tests.test_pure en push/PR a main)
  ahora vive en main. Rama feature 100% mergeada. Deuda restante flageada: U7.3 (cancel_handler/streamer/
  set_current_proc, acoplado a claudecli).

### U8 — Dispatch consistente del agente (hardening del arranque, 2026-06-24) — CONSTRUCTION ACTIVA
- **Disparador**: bug "coin-flip del dispatch" — `saga-ctl start` deja al agente fuera del room de forma
  intermitente → Win+Z `FileNotFoundError`/`ConnectionRefusedError`. "A veces anda, a veces no."
- **Causa raíz MEDIDA** (no timing): worker en modo prod con `load_threshold=0.7` → se auto-marca
  `unavailable` cuando la CPU local cruza 0.7 → si `create_dispatch` cae en esa ventana → `503 no response
  from servers`. El load-shedding es para POOLS de workers; saga = 1 worker/1 usuario → no aplica.
  **El retry de 90s en vcctl.py (working tree sin commitear) es un PARCHE que U8 descarta** (no se commitea).
- **Diseño** (4 cambios nativos, ver `construction/U8-dispatch-consistente/functional-design.md`):
  C1 `AgentServer(load_fnc=lambda:0.0, drain_timeout=0)` (worker siempre disponible + stop sin draining-zombie)
  · C2 dispatch AUTOMÁTICO nativo (`@server.rtc_session()` sin agent_name + eliminar `_ensure_agent_dispatched`
  + `LIVEKIT_AGENT_NAME`) · C3 server+worker SIEMPRE frescos en `start` + reordenar (browser antes del
  wait-socket) · C4 `close_on_disconnect=False` (socket Win+Z sobrevive recarga de pestaña).
- **Stages**: Functional Design CERRADO · NFR/Infra/UnitDesign = SKIP · Code Generation Part 1 (plan) +
  **Part 2 (código) HECHOS** (aprobado por el usuario, condicional a la garantía de no-regresión).
  Código: `lk/agent.py` (load_fnc=0/drain_timeout=0/num_idle_processes=1 + auto-dispatch + pop env +
  close_on_disconnect=False), `vcctl.py` (eliminada `_ensure_agent_dispatched` → helper `_kill_pids`;
  `_start_room` server+worker frescos + browser→wait-socket, sin dispatch API; neto −150 líneas),
  `vc/config.py` (eliminada `LIVEKIT_AGENT_NAME`), `orb_server.py` (comentario). Docs: `.claude/CLAUDE.md`
  + 7 archivos (docs/*, README, lk/README). Step 0: tests.yml espurio revertido. Toda la API verificada
  contra livekit-agents 1.6.0 instalado (inspect/getsource), no de memoria. Summary:
  `construction/U8-dispatch-consistente/code/generation-summary.md`.
- **Verificación estática CERRADA**: py_compile TODO OK + import smoke + tests.test_pure 11/11 + grep refs
  muertas=0 en código. Análisis de impacto (grep): wake/orbe/turnos/LLM/STT FUERA del diff (no se rompen).
- **Build & Test EN VIVO — VALIDADO 100% por el usuario (2026-06-24)**: arrancó de 0, restart, uso real →
  NO se rompió, "funcionó bien". **Cold boot del SO COMPLETADO**: reinició toda la PC, saga levantó limpio,
  "funciona perfectamente, no hay errores, super consistente y prolijo". U8 CERRADO — sin pendientes.
- **Docu pendiente RESUELTA (2026-06-24)**: `docs/README.md` (puerta de entrada) estaba stale — describía
  "fallbacks console y clásico" (eliminados en U7) y no mencionaba el modo único room / dispatch automático.
  Corregido: ahora dice "modo único transporte ROOM + dispatch automático nativo". Era el único gap de la
  verificación de sincronización docs↔código (resto 100% alineado, U8 cubierto en 6/7 archivos → ahora 7/7).
- **Build and Test U8 — CERRADO OK** (2026-06-24). Commit + push autorizados por el usuario.

## ESTADO GLOBAL (2026-06-24)
**Ciclo 4 (console→room) CERRADO Y MERGEADO A MAIN** (PR #1, merge 01b7161). Incluye U1–U7 + U7.1
(limpieza + fix race/cold-start) + U7.2 (cadena muerta runtime) + CI. Doc 100% alineada. Validado en vivo.
**U8 — dispatch consistente CERRADO Y VALIDADO 100% EN VIVO** (hardening del arranque, causa raíz =
load_threshold; auto-dispatch nativo). Cold boot del SO OK. Docu de entrada (`docs/README.md`) alineada.
Mergeado a main (PR #2). Deuda menor: U7.3 (cancel/proc machinery), fine-tune wake (Ciclo 2
diferido), `Executor shutdown` del wake detector al bajar.

## U9 — Cap threads ONNX (CPU del wake) — CERRADO Y VALIDADO 10/10 (2026-06-24)
- **Problema**: worker a ~410% CPU en idle. Causa raíz (docs oficiales onnxruntime + entorno): ONNX abre
  1 thread/core y los hace SPIN (busy-wait) entre inferencias → el wake "hey saga" (modelo 169 KB, infiere
  ~cada 240ms) quemaba ~367% CPU con 50 threads sin computar.
- **Fix**: `lk/onnx_tune.py` `cap_onnx_threads()` parchea `ort.InferenceSession` (intra/inter=1 +
  `session.intra_op.allow_spinning=0`), llamado en `agent.py` antes de cargar modelos. Idempotente +
  degradación segura. `OMP_NUM_THREADS` descartado (onnxruntime 1.26 sin OpenMP → única vía SessionOptions).
- **Resultado MEDIDO en vivo**: CPU worker **410% → 40%** (10x). Wake 367%/50thr → 3.5%/1thr. RAM 2757→2441 MB.
  Detección intacta (usuario 10/10: "me detecta la voz igual, no veo fallos"). Sin tocar features.
- **Fuera de scope**: RAM del turn detector semántico (~1.8 GB) = fix C (turn detector → VAD puro), otro ciclo.
  Split Pi (browser/mic vs worker) + onnxruntime-web para el wake = deploy hardware chico, futuro.
- **Mergeado a main** (PR). Ciclo 5 (tools/MCPs) sigue ABORTADO/diferido (el spike mostró boot storm + ROI dudoso).

## Ciclo 5 — saga agéntico (cargar plugins en Claude) — **CERRADO (2026-06-25)**
> **CERRADO Y VALIDADO EN VIVO.** Spike completo: medición A/B (off vs full) + auditoría + 2 bugs hallados.
> **Veredicto:** cargar plugins FUNCIONA; con blacklist agresiva (4 MCPs) el overhead es +1-2s/turno (tolerable,
> vs 10x del full completo). saga YA es agéntica con built-ins (en `off` respondió "último partido de la
> selección" vía WebSearch, sin plugins). **Decisión del usuario:** deja los plugins activos por ahora
> (`VOICE_FULL_STACK=1` en `.env.local`) — "me gustan, los MCPs son prácticos"; el DEFAULT del código sigue
> `0` (reversible). **PENDIENTE (futuro):** definir qué plugins/MCPs son realmente útiles para saga según su
> propósito (el usuario lo va a meditar). **Bug arquitectónico abierto:** TTS de Deepgram timeoutea en
> respuestas largas con tools (pausas matan el stream) → fix = frankenstein, NO se hizo.
>
> **Entregables (código, sin commitear aún — pendiente OK del usuario):** toggle `VOICE_FULL_STACK` (master
> switch env) + blacklist `configs/plugins-blacklist.json` (17 baneados) + `tools/measure_stack.py` (atribución
> RSS/CPU/TTFT) + watchdog `_PROC_TIMEOUT` 18→60s + `load_dotenv` movido al top de config.py (las `VOICE_*`
> ahora viven en `.env.local`). Todo reversible, default off.
>
> --- histórico ---
> El spike previo (`VOICE_FULL_STACK`) fue ABORTADO + REVERTIDO (boot storm sobre worker saturado, pre-U9).
> Re-abierto tras U9/U10. El toggle ya NO existía en el código (cero refs) → se reimplementó.

### Reality-check (registrado en requirements)
- **U9 ≠ fix del boot storm.** U9 capeó CPU del WORKER (wake ONNX). El boot storm venía de los MCPs pesados
  del STACK DE CLAUDE (`claude_daemon`, otro proceso: playwright/Chromium, npx, Google MCPs timeout). Cargas
  ORTOGONALES → el ciclo MIDE, no asume. Costos permanentes: arranque daemon más lento (~7s→~57s) + tool-defs
  por turno en contexto.

### INCEPTION Ciclo 5
- [x] Workspace Detection — RESUME (brownfield)
- [x] **Requirements Analysis — COMPLETO Y APROBADO** (ciclo5-agentic-requirement-questions.md +
  ciclo5-agentic-requirements.md). Decisiones: Q1=A (spike de medición primero) · Q2=C resuelto
  (full-stack-first como INSTRUMENTO; lista curada de plugins viables = ENTREGABLE, no input) · Q3=A (toggle
  reversible default OFF, **por ENV** — confirmado al usuario: es el patrón de toda la config de saga) · Q4=C
  (gate estabilidad + latencia, abort si rompe) · Q5 (seguridad mínima: god-mode + `vc/guard.py` + regla en prompt).
  **Hallazgo Q5**: el plugin borrado era **safety-net** (v0.8.2, marketplace cc-marketplace) = PreToolUse Bash
  hook anti-destructivo; **saga ya lo replica en `vc/guard.py`** → re-descargar = redundante. Gap real = tools
  MCP no-Bash (efectos externos) que el guard no intercepta.
  Extensiones: Security/Resiliency/PBT = **No** (ver Extension Configuration).
- [x] **Workflow Planning — COMPLETO Y APROBADO** (execution-plan-ciclo5.md). Stages a ejecutar: Code
  Generation + Build&Test. SKIP: User Stories / App Design / Units / Functional / NFR Req / NFR Design /
  Infra (spike de config single-component). Riesgo Low (código) / Medium (boot storm en vivo). Reversible
  (default OFF). Ajustado tras objeción del usuario: + observabilidad de ATRIBUCIÓN (FR3.1/FR3.2).

### CONSTRUCTION Ciclo 5
- [x] Functional/NFR Req/NFR Design/Infra Design — SKIP (sin lógica/modelos/infra nuevos).
- [x] **Code Generation Part 1 (plan) — COMPLETO** (construction/plans/ciclo5-code-generation-plan.md).
  5 pasos: (1) toggle granular `VOICE_FULL_STACK` off/full/selective en `vc/config.py`; (2) log del modo;
  (3) harness `tools/measure_stack.py` (RSS/CPU por MCP + TTFT del saga.log); (4) doc operativo de la prueba;
  (5) verificación estática. Hallazgo clave: el daemon hereda env (`prewarm_claude` env={**os.environ}) →
  vcctl/daemon NO se tocan; cambio aislado a config + 1 script. Reversible (default OFF idéntico al actual).
- [x] **Code Generation Part 2 (código) — HECHO** (REVISADO en Build&Test tras 2 objeciones del usuario).
  Modelo final = toggle `VOICE_FULL_STACK` off/full + granularidad **a NIVEL PLUGIN** (no MCP). (1)
  `vc/config.py`: `VOICE_DISABLED_PLUGINS` (csv, default playwright) → `.saga-settings.json` con guard +
  `enabledPlugins:false`, inyectado por `--settings` SOLO al daemon (PER-SAGA, NO toca `~/.claude/settings.json`).
  Descartado el modelo MCP-only (`--strict-mcp-config`/`.mcp-selective.json`): unidad equivocada. `.guard-settings.json`
  → renombrado `.saga-settings.json` (gitignore actualizado). (2) `claude_daemon.py`: log `stack=` + `off=<plugins>`.
  (3) `tools/measure_stack.py` (RSS/CPU por MCP + TTFT). (4) doc `how-to-measure.md`.
  **VERIFICADO el mecanismo en vivo**: `--settings enabledPlugins:false` saca el plugin de `claude mcp list`
  per-sesión (playwright 1→0). **Estática VERDE**: py_compile · flags off/full correctas · `.saga-settings.json`
  bien formado (guard+enabledPlugins) · override `VOICE_DISABLED_PLUGINS=""` ok · import daemon · tests 11/11.
  **CORRECCIÓN registrada**: deshabilité playwright GLOBAL por error (`claude plugin disable`, scope user) →
  REVERTIDO (`enable`, vuelve a true); el control quedó a nivel código/env de saga, como pidió el usuario.
- [ ] **Gate de aprobación de Code Generation (revisado) — PENDIENTE** (usuario).
- **Comparativa de recursos (medida)**: off=2 procs/240 MB · full−17baneados=6 procs/643 MB · full=11 procs/1044 MB.
  TTFT: off ~1.5s (baseline) · full−17 sin tool 4-6s, con tool 9-26s · full sin tool 13-17s. La carga de plugins
  cuesta latencia (contexto inflado por tool-defs); con tool, además, round-trips irreducibles.
- [x] **Build & Test — CERRADO (validado en vivo, A/B + auditoría)**. Flujo validado END-TO-END (restart sin inline → toma `stack=full`
  desde `.env.local`; `off=playwright` desde la blacklist JSON; árbol del daemon 11 procesos sin playwright).
  Sin boot storm (load 2.5/8, CPU ~1%); stack ~1.04 GB (claude 247, context7 199, mcpvault 190, exa 188,
  claude-mem 122). **TTFT en full (señal preliminar)**: primer turno `ttft=5.592s` vs ~1.4-2s normal stripped
  → el stack infla el TTFT (tool-defs en contexto), como se predijo; un turno siguiente dio 0.47s (corto).
  Falta confirmar el patrón con más turnos de voz del usuario + ver si saga usa tools.
- **Fix colateral (bug que destapó el usuario)**: `.env.local` se cargaba DESPUÉS de leer las `VOICE_*`
  → no se podían setear ahí. Movido `load_dotenv` al TOP de config.py → ahora todas las `VOICE_*` viven en
  `.env.local`. `VOICE_FULL_STACK=1` agregada ahí. Verificado: STACK_MODE=full sin inline; LIVEKIT keys OK.
- **BUG REAL hallado (Build&Test, systematic-debugging)**: el watchdog `_busy` (lk/agent.py:206,
  `_PROC_TIMEOUT=18.0`) mata turnos con tool/MCP con "no te entendí" — no distingue colgado de trabajando.
  Causa agravante: full stack lleva el TTFT de ~1.5s (stripped) a **13-17s** (~10x) por tool-defs en contexto;
  turnos con tool suman round-trips → cruzan 18s. Fix ideal a futuro = condition-based (heartbeat/tool_use
  resetea el watchdog). **APLICADO (decisión del usuario, pragmático): `_PROC_TIMEOUT` 18→60s** (lk/agent.py),
  red de seguridad para cuelgues reales, no presupuesto de latencia (el daemon corta a 180s). py_compile OK +
  CLAUDE.md gotcha actualizado. Validación en vivo pendiente.
- **Reducción de carga (1er experimento)**: blacklist ampliada a **17 plugins** (deja solo github +
  claude-obsidian). Árbol del daemon **11→6 procesos**, RAM **1044→637 MB (−40%)**. Quedan exa-mcp + mcpvault
  (obsidian) = MCPs STANDALONE (no plugins → la blacklist no los toca); github es HTTP remoto (sin proceso).
  TTFT post-reducción = pendiente (turno de voz del usuario). Si sigue >18s con tool → hace falta el fix del watchdog.
- [x] **REDISEÑO del control de plugins (3x, por el usuario) — HECHO**. Modelo final: env `VOICE_FULL_STACK`
  = master switch (0=claude a secas / 1=stack) + blacklist **`configs/plugins-blacklist.json`** (editable,
  `{"disabledPlugins": ["name@marketplace", ...]}`, escala a N). **Sacado el hardcode** `_DEFAULT_DISABLED` y la
  env-csv `VOICE_DISABLED_PLUGINS`. JSON elegido sobre txt (coherente con el formato nativo de Claude Code
  `enabledPlugins`; el destino `.saga-settings.json` ya es json → cero conversión). Verificación estática VERDE
  (parser ignora `_comment`, degrada a [] si JSON roto, flags off/full, `.saga-settings.json` bien formado,
  tests 11/11). Falta restart para aplicar el nuevo código.

### Spike (a reimplementar en Construction)
- Toggle env reversible (default OFF) en `vc/config.py` que saltea `--setting-sources ''` → carga el stack.
- Instrumentación reusada (NO se agrega): boot del daemon (`claude_daemon.py`); TTFT/turno (`lk/agent.py` → `saga.log`).
- MCPs que cargaría el full stack: Gmail, Google Calendar/Drive, exa, monton, obsidian-vault, claude-mem,
  context-mode, context7, github, playwright, vercel. Pesados/externos: playwright, Google*, github, vercel.

## Ciclo 3 — Fix buffer de audio + feedback "no hay voz"
- **Tipo**: bugfix + enhancement UX, brownfield. RE vigente → skip RE.
- **Problema**: el mic acumula audio en idle (set_audio_enabled no detiene la captura en console) → al
  abrir, backlog de ~121s → VAD/away se ahogan → orbe pegado en "Grabando".
- **Decisiones** (2026-06-23, ver buffer-fix-requirement-questions.md):
  - Q1 mecanismo: `clear_user_turn()` (nativo). pause/resume DESCARTADO (API interna peligrosa).
  - Q2 feedback: SÍ, amarillo "No te entendí" (estado `error` del orbe) cuando no hay voz.
  - Q3 scope: reactivar wake al final + validar en vivo.
- **Restricción dura**: NO tocar buffers/streaming a mano. Solo API/config nativa LiveKit.

### INCEPTION Ciclo 3
- [x] Workspace Detection / Reverse Engineering — reutilizados (brownfield vigente)
- [x] Requirements Analysis — COMPLETO (buffer-fix-requirement-questions.md)
- [x] User Stories / Application Design / Units Generation — SKIP (bugfix acotado, entregable único)
- [x] Workflow Planning — execution-plan-ciclo3.md

### CONSTRUCTION Ciclo 3
- [x] Functional/NFR/Infra Design — SKIP
- [x] Code Generation — se intentó (clear_user_turn reordenado, reset away timer, amarillo error)
- [x] Build and Test — **REVERTIDO. Diagnóstico = entregable del ciclo.**
  - **Resultado**: los parches NO resolvieron y empeoraron el flujo (cada fix tapaba un borde y el backlog
    abría otro: away prematuro, "Pensando" colgado con audio vacío, respuestas a ruido fantasma).
  - **Decisión del usuario (2026-06-23)**: ROLLBACK. `git checkout lk/agent.py lk/claude_llm.py` al commit
    estable 4743056. Sin parches del Ciclo 3, sin orbe amarilla. Wake queda ACTIVO (la detección "hey saga"
    anda bien; lo que falla es el flujo post-captura por el buffer).
  - **CAUSA RAÍZ (firme, verificada 3x + research)**: en modo console `set_audio_enabled(False)` NO detiene
    la captura → el `rtc.AudioStream` (livekit-core C++) acumula audio en idle (backlog medido: 72s, 23s,
    12s, 4.7s — intermitente). El buffer es OPACO: no se purga desde Python. `clear_user_turn` no alcanza.
    Con backlog, el STT transcribe ruido como texto fantasma → flujo roto.
  - **FIX REAL (Ciclo futuro)**: salir del modo console. Opciones a investigar: (a) otro modo de LiveKit
    (worker/room real) donde el input track se conecta/desconecta de verdad; (b) capturar la consulta con
    stream propio (portaudio, como el wake y el modo viejo) + STT, sin pasar por el pipeline de audio de
    LiveKit en console. Es rearquitectura, no parche.
  - **Estado actual**: código = commit estable. Wake ACTIVO (`SAGA_WAKE_ENABLED=1`). Limitación del buffer
    conocida y documentada. Win+Z andando.

## Ciclo 2 — Wake word "hey saga" (ENTREGADO 2026-06-23)
- Feature implementada + modelo (FPPH=0) + docs, **commiteado y pusheado** (commit 4743056).
- Wake OFF por default: bloqueado por el bug del buffer → se resuelve en Ciclo 3.

## Ciclo 2 — Wake word "hey saga"
- **Tipo**: feature, brownfield. RE vigente (ciclo 1) → skip RE.
- **Problema**: Vosk = falsos positivos masivos. Evaluar alternativa.
- **Research hecho**: livekit-wakeword (recomendado, nativo a LiveKit, 100× menos falsos+ que openWakeWord), openWakeWord (plan viejo), Porcupine (cerrado), microWakeWord (ESP32/futuro).
- **Decisiones tomadas** (2026-06-22):
  - Engine wake: livekit-wakeword (pre-decidido)
  - Mic: toggle/opt-in (B) — Win+Z sigue primario
  - ~~Training: synthetic-only (A)~~ → **CORREGIDO post-Build&Test: synthetic positives (VoxCPM) +
    ACAV100M real negatives (2000h)**. Synthetic-only falló (falsos+ masivos por falta de negativos reales).
  - Frase: "hey saga" (A)
  - Speaker verify: diferido a Ciclo 3 (B)

### INCEPTION Ciclo 2
- [x] Workspace Detection — reutilizado de Ciclo 1
- [x] Reverse Engineering — reutilizado de Ciclo 1 (brownfield, vigente)
- [x] Requirements Analysis — Completo 2026-06-22 (Q2=B, Q3=A, Q4=A, Q5=B, Q1 diferido C3)
- [ ] User Stories — SKIP (feature pequeña, sin ambigüedad de scope)
- [x] Workflow Planning — Aprobado 2026-06-22 (execution-plan-ciclo2.md)
- [ ] Application Design — SKIP (sin componentes/servicios nuevos)
- [ ] Units Generation — SKIP (entregable único)

### CONSTRUCTION Ciclo 2
- [x] Functional Design — SKIP (hook directo wake→press, sin lógica compleja)
- [x] NFR Requirements — SKIP (extensiones off)
- [x] NFR Design — SKIP
- [x] Infrastructure Design — SKIP (pip package local, sin cloud)
- [x] Code Generation — Completo 2026-06-22 (lk/wakeword.py NEW · lk/agent.py MOD · scripts/train_wakeword.py NEW · pyproject.toml MOD)
- [x] Build and Test — **CERRADO OK 2026-06-22**. Iteración final (piper positives + ACAV100M 2000h real):
  **FPPH=0.00, Recall=98.5%, AUT~0** (validación 17.27h, 31k negativos reales). Verificado en vivo: 0 falsos
  positivos en 60s de ambiente (el modelo synthetic-only flasheaba cada 2s). Wake habilitado
  (`SAGA_WAKE_ENABLED=1`, `SAGA_WAKE_THRESHOLD=0.5`). Beep de feedback cableado. Pendiente: confirmación en
  vivo del usuario que su voz dispara el wake (la mitad cross-speaker que requiere hablar).
  - Iteraciones: (1) piper sin ACAV → FPPH 54; (2) VoxCPM sin ACAV → scores solapados; (3) VoxCPM+ACAV →
    abortada (VoxCPM 51s/clip en CPU = 71h inviable); (4) **piper+ACAV → FPPH 0, ganadora**.
  - Nota técnica: VoxCPM (difusión) inviable en CPU sin GPU. piper positives = misma calidad efectiva porque
    el fix real son los negativos reales (ACAV), no el TTS. Es la receta canónica de openWakeWord pre-trained.
  - **Validación en vivo (usuario)**: 0 falsos positivos (excelente), PERO recall marginal en la voz del
    usuario — scores 0.06-0.13, requiere estar cerca del mic. Causa: positivos sintéticos (voces inglesas)
    no cubren bien el acento rioplatense. Threshold estable = 0.06 (a 0.04 flashea).

### CONSTRUCTION Ciclo 2 — Debug en vivo (2026-06-22 noche)
Síntomas reportados: orbe pegado en "Grabando", wake "solo si hablás lento", scores bajos.
**Causa raíz (verificada en log)**: el mic de laptop capta ruido de fondo continuo (STTMetrics de 5s
ininterrumpidos por ~90s). El silero VAD (activation_threshold 0.5) lo veía como voz → nunca detectaba
silencio → el turno no cerraba → orbe pegado en rec (reflejaba la realidad: SÍ seguía grabando). El mismo
ruido degrada los scores del wake y obliga a hablar lento/claro. NO era la voz, el acento ni el modelo.
Fixes aplicados:
- `lk/agent.py`: `silero.VAD.load(activation_threshold=0.6)` — filtra el ruido de fondo.
- `lk/agent.py`: watchdog de grabación (REC_TIMEOUT=6s) — si entrás en rec y no hablás, vuelve a idle solo
  ('no entendí'). Recupera comportamiento del flujo clásico + red de seguridad anti-orbe-colgado.
- `lk/agent.py`: log de `agent_state_changed` (debug de la máquina de estados).
Otros hallazgos: TTS APITimeoutError (Deepgram, transitorio de red); el "orbe blanco" es el estado rec
normal (núcleo brillante por diseño), no un bug de render.
Pendiente: validación en vivo del usuario (orbe vuelve a idle en los 2 casos).

### BUG ABIERTO — buffer de audio acumulado en idle (modo console LiveKit)
**Severidad**: alta (bloquea el wake en uso real). **Estado**: diagnosticado, sin fix.
**Síntoma**: al disparar el turno (wake o Win+Z), el orbe queda "Grabando" indefinidamente; el VAD/away
tardan o no cierran; saga responde pero el flujo no vuelve a idle.
**Causa raíz (confirmada en log + código)**: en modo console, `session.input.set_audio_enabled(False)`
NO detiene la captura física del mic — el audio se sigue acumulando en un buffer durante el idle. Al abrir
el mic, LiveKit entrega TODO el backlog de una (medido: audio_duration=121s tras 123s en idle; 40s, 23s,
13s en otros casos — el nº coincide con el tiempo en idle). El VAD y el `user_away_timeout` no pueden
detectar "silencio actual" mientras procesan minutos de audio viejo → el cierre se ahoga.
**Lo que NO lo arregla** (ya probado): subir VAD activation_threshold (0.5→0.6→0.7, ayuda con ruido vivo
pero no con el backlog); `user_away_timeout=6.0` nativo (no cuenta mientras procesa el backlog); watchdog
manual (causó session_error por race, revertido).
**Pistas para el fix** (research previo): `clear_user_turn(stt_flush_duration=...)`, el "pre-connect audio
buffer" en room_io/_input.py (líneas 340-357), `on_attached/on_detached` del audio_stream según
audio_enabled (io.py:442-462). Hipótesis: en console el track no se detacha físicamente; habría que
descartar el buffer al entrar en rec, o cambiar cómo se controla el mic (conectar/desconectar el track
real en vez de set_audio_enabled). Requiere research dedicado de la API console de LiveKit.
**NFR**: el fix NO debe tocar el pipeline de streaming a mano (decisión del usuario) — usar mecanismos
nativos de LiveKit.

### Fixes aplicados esta sesión (quedan, son mejoras válidas)
- `lk/agent.py`: `_WAKE_ENABLED` — bug `bool("0")==True` arreglado (SAGA_WAKE_ENABLED=0 ahora apaga de verdad).
- `lk/agent.py`: VAD `activation_threshold=0.7` (filtra mejor el ruido del mic de laptop).
- `lk/agent.py`: `user_away_timeout=6.0` nativo + handler `user_state_changed -> away` (vuelve a idle si no
  hablás). Funciona parcialmente; limitado por el bug del buffer.
- `lk/agent.py`: log de `agent_state_changed` (debug; se puede quitar cuando se cierre el bug).

### Estado del wake (fin de sesión 2026-06-22 noche)
Wake **DESHABILITADO** (`SAGA_WAKE_ENABLED=0`). Win+Z es el trigger. El modelo `hey_saga.onnx` (FPPH=0,
ACAV) queda entrenado y listo; el blocker para activarlo es el bug del buffer, NO el modelo.

### CONSTRUCTION Ciclo 2 — Sub-iteración: fine-tune con voz real (DIFERIDO)
> Diferido: el cuello de botella real resultó ser el buffer de audio + ruido de mic, no el recall del
> modelo. El fine-tune con voz real sigue siendo válido (sube recall + alimenta Ciclo 3) pero se retoma
> DESPUÉS de resolver el bug del buffer. Script de grabación `scripts/record_wakeword.py` ya está listo.
- **Decisión usuario (2026-06-22)**: encarar fine-tune con grabaciones reales. Doble propósito: (a) sube el
  recall del wake en la voz del usuario (0.06 → ~0.8+); (b) las mismas grabaciones alimentan speaker
  verification (Ciclo 3) — sin trabajo duplicado.
- **Channel matching**: grabar con el mismo mic de uso (laptop), distancia real, variando condiciones.
- [x] Code Generation — `scripts/record_wakeword.py` (graba N muestras 16kHz mono, resume, guía de variación,
  feedback de nivel). Compila + smoke OK (mic abre a 16kHz nativo).
- [ ] Grabación — PENDIENTE (requiere al usuario: correr el script y hablar). No automatizable.
- [ ] `scripts/finetune_wakeword.py` — PENDIENTE (mezclar grabaciones + dataset, reentrenar).
- [ ] Reentrenamiento + validación en vivo.

## Execution Plan Summary
- **Total Stages**: 13 (5 INCEPTION hechas/decididas, Construcción definida)
- **Stages to Execute**: Code Generation (=> archivos `docs/`), Build and Test (=> verificación de doc)
- **Stages to Skip**: User Stories, Application Design, Units Generation, Functional Design,
  NFR Requirements, NFR Design, Infrastructure Design — todas N/A para un entregable de
  documentación sin cambios de código. Operations = placeholder.

## Backlog / Ciclos futuros

### Ciclo (futuro) — saga como servicio de voz HEADLESS / LAN (NO encarar TODAVÍA, 2026-06-24)
> **Decisión del usuario: NO tocar ahora.** Hoy saga vive DENTRO de su PC (asistente de escritorio) y así
> está perfecto. Esto queda documentado para el día que se quiera correr en una mini PC / Raspberry Pi 24/7.
- **Por qué NO sale "tal cual está"** (verificado en código, 2026-06-24): dos supuestos rompen la premisa de
  "mini PC headless con mic":
  1. **El mic lo lee el BROWSER, no el server.** `lk/wakeword.py` consume el `rtc.AudioStream` del track que
     publica el browser (getUserMedia). Ningún proceso de saga lee hardware de audio. Sacar el monitor ≠ sacar
     el browser: el browser es el DISPOSITIVO DE AUDIO (mic in + TTS out), no solo la UI del orbe.
  2. **Todo bindeado a loopback A PROPÓSITO** (privacidad/seguridad): LiveKit signaling `bind_addresses:
     127.0.0.1` (`livekit.yaml`), `orb_server` en `127.0.0.1`, y el `/token` devuelve `ws://127.0.0.1:7880`.
     "Conectarse desde otra PC de la LAN" NO sale sin reconfigurar esos 3 binds + el token + sumar AUTH (hoy
     el loopback ERA la seguridad → exponerlo abre el room a cualquiera de la red).
- **Dos escenarios viables** (elegir cuando se encare):
  - **A — mini PC = backend; browser+mic+parlantes en otra PC de la LAN.** Falta: exponer signaling+orb_server
    a `0.0.0.0`, token con IP real de la mini PC, AUTH de red. El mic/parlante son los de la PC cliente.
  - **B — mini PC = todo; hablarle a su mic físico, headless.** Falta: browser kiosk corriendo EN la mini PC
    (display virtual Xvfb + audio Pipewire + autostart) que abra el orbe local. Ahí el loopback alcanza.
- **Transversal a ambos (capa de servicio que hoy NO existe)**: supervisión de procesos (systemd units +
  `Restart=always` + arranque al boot + watchdog/healthcheck que reinicie la pieza muerta), rotación de logs
  (`saga.log` crece infinito), y en ARM/RPi **Deepgram OBLIGATORIO** (faster-whisper+onnxruntime en CPU ARM =
  inusable) + validar wheels ARM de los plugins. Wake word con deuda abierta (Executor-shutdown al bajar +
  recall marginal rioplatense 0.06-0.13) → no confiable como trigger 24/7 sin fine-tune.

### Orbe — sync real con audio TTS
- **Problema**: animación actual es sintética (audioLevel falso por estado), no refleja el audio real.
- **Intentado**: metering RMS → POST /level → SSE → browser. Descartado: lag inevitable HTTP entre pacat y browser.
- **Opciones viables**:
  1. **Electron/Tauri** (desktop app): acceso a Web Audio API nativa + AnalyserNode sobre audio del sistema. Sync perfecto. Cambio arquitectónico grande — app de escritorio en vez de browser.
  2. **Browser como participante LiveKit**: el orbe se conecta al room LiveKit y recibe el track TTS de audio. Usa AnalyserNode directamente sobre el track. Factible dentro del stack actual, trabajo considerable.
- **Decisión 2026-06-22**: ambas opciones consideradas. Se mantiene browser por ahora. Electron/Tauri queda como posibilidad futura si la app crece a desktop completo. Opción 2 es el camino preferido si se implementa dentro del stack web.

## Workspace State
- **Existing Code**: Yes
- **Programming Languages**: Python 3.12 (28 archivos .py), JavaScript/HTML (orbe Three.js)
- **Build System**: setuptools (pyproject.toml) + lock pip (requirements.txt)
- **Project Structure**: Monolito modular (paquete `vc/` + paquete `lk/` + daemons de raíz + orbe web)
- **Reverse Engineering Needed**: Yes
- **Workspace Root**: /home/renzo/.local/share/saga

## Code Location Rules
- **Application Code**: Workspace root (NUNCA en aidlc-docs/)
- **Documentation**: aidlc-docs/ solamente
- **Structure patterns**: ver code-generation.md Critical Rules

## Extension Configuration
| Extension | Enabled | Decided At |
|---|---|---|
| Security Baseline | No | Requirements Analysis |
| Resiliency Baseline | No | Requirements Analysis |
| Property-Based Testing | No | Requirements Analysis |

> Notas: las tres se saltan como gate bloqueante (scope = documentación + plan, sin código nuevo).
> Security y PBT-partial quedan cubiertos como *recomendaciones* en el plan de remediación.
> Reglas completas de extensiones NO cargadas (todas opt-out).
> **Ciclo 8 (2026-07-12): re-confirmado por opt-in explícito** (delegado al AI) → Security=B(No),
> Resiliency=B(No), PBT=C(No). Justificación en ciclo8-cleanup-requirements.md: el ciclo BORRA código
> muerto, sin superficie de red/auth/secretos ni funciones puras/serialización nuevas. Compliance
> summary del ciclo: las 3 = **N/A** (no aplican al cleanup), no bloquean.

## Stage Progress

### INCEPTION
- [x] Workspace Detection — Completado 2026-06-21T22:49:10Z
- [x] Reverse Engineering — Aprobado 2026-06-21T22:49:10Z (review delegada; 1 fix aplicado)
- [x] Requirements Analysis — Completo 2026-06-21T22:49:10Z (User Stories incluido por pedido del usuario)
- [x] User Stories — **SKIPPED** por decisión del usuario (tarea de documentación; las historias agregaban ceremonia sin payoff). Artefactos de planning quedan como histórico, sin uso.
- [x] Workflow Planning — Aprobado 2026-06-21T22:49:10Z (alcance docs/ = FULL, 7 archivos)
- [ ] Application Design — **SKIP** (no hay componentes/servicios nuevos)
- [ ] Units Generation — **SKIP** (sin descomposición; entregable único)

### CONSTRUCTION
- [ ] Functional Design — **SKIP** (sin lógica/modelos nuevos)
- [ ] NFR Requirements — **SKIP** (extensiones opt-out)
- [ ] NFR Design — **SKIP**
- [ ] Infrastructure Design — **SKIP** (sin infra)
- [x] Code Generation — Part 1 aprobado (review delegada) + Part 2 generado: 7 archivos `docs/` + link en README + resumen. Esperando aprobación del entregable.
- [ ] Build and Test — **EXECUTE** → verificación de la documentación (siguiente)

### OPERATIONS
- [ ] Operations — PLACEHOLDER (fuera de scope)

## Reverse Engineering Status
- [x] Reverse Engineering (v1) - Completado y aprobado 2026-06-21T22:49:10Z (STALE — describía modo console + flujo clásico)
- [x] Reverse Engineering (REFRESH) - **CERRADO 2026-07-12** (8/8 artefactos). Refresh de artefactos 2026-07-11
  (7/8) + code-quality-assessment refrescado 2026-07-12 + auditoría de consistencia de los 7 contra código real
  (HEAD 57399b3): drift corregido en api-documentation (is_goodbye/vc.tts), component-inventory
  (WakeWordTrackDetector ubicación, /events vs /state, sound.py vivo, test_pure real, say.py→measure_stack),
  technology-stack (CI existe, wake en worker), business-overview (wake en worker), dependencies (vc/app.py NO
  es stub). architecture + code-structure = 100% consistentes sin cambios. Motivo del refresh: v1 obsoleto tras
  Ciclo 4 (room), U7 (borra console/clásico), U8 (dispatch auto), U9 (cap ONNX), U10 (VAD puro), U11 (CLAUDE_PLUGINS).
- **Artifacts Location**: aidlc-docs/inception/reverse-engineering/

## Doc-sync 2026-07-12 — CERRADO
Objetivo: documentación de TODO el proyecto consistente con el código actual (HEAD 57399b3, U11).
- **docs/ (7 archivos + READMEs + CLAUDE.md)**: auditados contra código. Veredicto = notablemente al día
  (turn_detection="vad", CLAUDE_PLUGINS, _PROC_TIMEOUT=60, puertos, dispatch auto, console/clásico solo como
  historia — todo coincide). Único drift real: `docs/tech-debt-plan.md` listaba D4 (`is_goodbye`) y D5
  (`import os` duplicado) como deuda abierta, pero el código ya las resolvió (U7). FIJADO: ambas marcadas
  ✅ Resuelta en tabla + plan.
- **aidlc-docs/reverse-engineering**: RE refresh cerrado (ver arriba).
- Nota no-drift (no tocada): tabla de latencia en turn-flow.md es snapshot histórico Ciclo 4 (auto-consistente);
  `pyproject.toml` aún declara `livekit-plugins-turn-detector` sin uso post-U10 (deuda de deps, no de docs).
