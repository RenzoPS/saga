# Guía del código (archivo por archivo)

Qué hace cada módulo y cómo encaja. Para el detalle a nivel función, los **docstrings del código
son densos y confiables** — leelos en el archivo.

## Raíz (entrypoints y daemons)

- **`saga.py`** — entrypoint fino de Win+Z. Delega en `vc.app.main`: emite el `press` al socket de
  control del agente (y expone `--doctor`). Es lo que llama el wrapper de Hyprland.
- **`vcctl.py`** (`saga-ctl`) — control del ciclo de vida: `start/stop/status/restart`. Mata por
  **basename/ruta exacta** leyendo `/proc` (nunca `pkill -f`, que se auto-mataría y pegaría en el
  `claude` CLI). **`_start_room()`** (único modo, Ciclo 4) orquesta server
  nativo → cerebro → orbe → worker → dispatch → browser con readiness por pieza. Helpers room: `_node_ip()` (IP LAN
  primaria por socket UDP, sin subprocess), `_livekit_server_pids()` (match basename `livekit-server`),
  `_ensure_agent_dispatched()` (borra dispatches huérfanos + `create_dispatch` por API → el agente
  entra al room antes que el browser). `stop` baja todo, incluido el binario nativo.
- **`claude_daemon.py`** — el cerebro caliente: mantiene UN proceso `claude` (stream-json)
  persistente entre turnos. Gestiona sesión (`--session-id` vs `--resume`), reintento ante sesión
  muerta, timeout por turno (180s), reset, anti doble-arranque, auto-apagado a 1h idle. **Cancel
  (Win+Z): si el cliente cierra el socket, mata el grupo entero (claude + subspawns claude-mem) y
  devuelve `"cancelled"`** (turno manejado, sin reintentar) → daemon libre sin zombie/huérfano; el
  próximo turno respawnea con `--resume` (contexto hasta el último turno completo intacto).
- **`wake_daemon.py`** — wake word con Vosk (local, offline). **DORMIDO, fuera de scope** (el wake
  activo es "hey saga" server-side en el agente, `SAGA_WAKE_ENABLED=1`).
- **`livekit.yaml`** — config del `livekit-server` NATIVO (modo room, Ciclo 4). Signaling bindeado a
  loopback (`port 7880`) + media en un puerto UDP (`udp_port 7882`). **Sin secretos** (las keys entran
  por la env `LIVEKIT_KEYS` que arma saga-ctl) y sin `node_ip` (lo inyecta saga-ctl por env `NODE_IP`
  = IP LAN, porque LiveKit nunca bindea el UDP a loopback). Versionable.

## `lk/` — modo LiveKit (room, único)

- **`lk/agent.py`** — el **worker** del modo room (`start`): conectado a `livekit-server`, el audio
  llega por el track del browser. Se registra como agente NOMBRADO con
  `@server.rtc_session(agent_name=...)` (dispatch EXPLÍCITO, no auto). Arma el `AgentSession`
  (STT+VAD+LLM+TTS) con TODA la config de turnos dentro de `turn_handling`: turn detector SEMÁNTICO
  (`MultilingualModel`, EOU multilingüe), `endpointing` min 2s, `interruption` por VAD local, y
  `preemptive_generation` **OFF** (sobre transcripts parciales rompía el LLM bloqueante). Implementa
  las 3 fases de Win+Z (`_press`), el prompt por texto (`_say`), el socket de control
  (`press`/`stage`/`say`), y los handlers de estado `_on_agent_state`/`_on_user_state`. **Timers
  propios** (`asyncio.call_later`, sin internals): `_arm_away` (6s "abriste el mic y no hablaste",
  VAD-aware) y `_arm_busy` (18s watchdog de turno colgado en thinking). BVC (noise cancellation) NO
  se usa: requiere LiveKit Cloud → falla en el server self-hosted; room se apoya en el VAD Silero.
  Además levanta orbe + precalienta Claude (dedup-safe). Plugins LiveKit importados a **nivel
  módulo** (deben registrarse en el main thread).
- **`lk/claude_llm.py`** — LLM custom de LiveKit = **el ÚNICO turn handler**. Reenvía el
  último turno del usuario a `claude_daemon`, engancha comandos de voz (reset, visión), consume
  adjuntos staged, y puentea el generador bloqueante de Claude a deltas asyncio. Cancelación en
  barge-in: al cancelar LiveKit el turno, setea el flag `_cancel` (que `claudecli`/daemon respetan)
  y espera al worker antes de limpiarlo.
- **`lk/whisper_stt.py`** — adaptador STT faster-whisper para LiveKit (fallback sin Deepgram).
- **`lk/edge_tts_plugin.py`** — plugin TTS edge-tts para LiveKit (fallback sin Deepgram).

## `vc/` — soporte (reusado por ambos modos)

- **`vc/config.py`** — **fuente única** de paths, flags, voces, system prompt (agéntico: usa las
  tools built-in tipo Bash), regex (reset/visual), y los args base de `claude`
  (`build_claude_base_args`, compartidos por daemon y one-shot). **Carga `.env.local` al importar**
  (idempotente) para que cualquier importador —incluido `orb_server`, que mintea el JWT— vea las
  keys. Constantes del modo room (Ciclo 4): `LIVEKIT_URL/API_KEY/API_SECRET/ROOM`,
  `LIVEKIT_AGENT_NAME` (dispatch explícito), `LIVEKIT_SERVER_BIN`/`LIVEKIT_CONFIG`/`LK_SERVER_LOG`,
  `LIVEKIT_SIGNAL_PORT` (7880). Las keys solo
  viven en `.env.local`; URL/room/agente tienen default local. Sin lógica.
- **`vc/claudecli.py`** — cliente de Claude con dos caminos: daemon (rápido) + fallback one-shot
  (`claude -p`). Maneja imagen (multimodal por stdin), reintento de sesión, y respeta el flag global
  de cancelación.
- **`vc/session.py`** — sesión uuid persistida (escritura atómica) + detección de keywords:
  `is_reset_command`, `is_visual_command`, `is_goodbye` (esta última quedó **sin uso** — código muerto).
- **`vc/attach.py`** — adjuntos del panel, **consume-once**: texto en memoria del proceso agente,
  imagen como path en `/tmp`. `take_staged()` consume en el turno.
- **`vc/desktop.py`** — integración Hyprland: `grim` (screenshot), monitor kitty con tail del log.
- **`vc/runtime.py`** — estado runtime compartido (evita ciclos de import): log rotativo (512KB),
  evento de cancelación, kill de proceso/streamer por grupo, **PID-files anti-recycle** (validan
  `starttime` de `/proc` para que un PID reciclado no se haga pasar por el dueño).
- **`vc/guard.py`** — hook **PreToolUse** de Claude: denylist de bash catastrófico (rm -rf, dd,
  mkfs, fork bomb, git reset --hard, sobrescribir dotfiles…). Fail-open. Función pura `denied()` testeable.
- **`vc/sound.py`** — beep de notificación (genera WAV de dos tonos, lo reproduce con `paplay`).
- **`vc/orb.py`** — cliente del orbe: levanta el server si hace falta y manda el **estado** por HTTP
  no bloqueante (cola + keep-alive). No manda nivel de audio: el orbe late con el track TTS vía Web
  Audio en el browser (no por este canal).
- **`vc/doctor.py`** — health check (`saga.py --doctor`): verifica binarios, deps, daemons, config.
  Read-only.
- **`vc/app.py`** — entrypoint de Win+Z (adelgazado): `main` parsea `--doctor` y emite `press` al
  socket de control del agente (`_livekit_toggle`). El flujo del turno vive en el agente (`lk/`).

## `orb/` — orbe visual

- **`orb/orb_server.py`** — server persistente (HTTP + SSE), stdlib. Sirve la página, emite estado
  por SSE, y hace de **puente HTTP→socket** para el panel (el browser no puede abrir un socket Unix).
  Endpoint **`/token`** (modo room): mintea el JWT con el que el browser se une al room
  (`livekit.api.AccessToken`, SOLO para unirse; el dispatch del agente lo hace `saga-ctl` por API,
  no el token — fuente de dispatch única); `livekit.api` se importa **lazy** dentro del handler. Sirve
  el vendor con MIME para `.mjs` (módulos ES). Watchdog que vuelve a idle si saga muere.
- **`orb/orb.html`** — render Three.js del orbe (estados acoplados por bloom) **+ cliente LiveKit**
  (Ciclo 4): pide `/token`, se une al room (`Room.connect`), publica el mic muteado (desmutea en
  `rec` vía el estado SSE) y recibe el track TTS. Con **Web Audio `AnalyserNode` sobre ese track
  (U5)** el orbe late con el nivel REAL de la voz (`window.__ttsLevel()`). Cuidado: colores de fondo
  en **sRGB** (`THREE.SRGBColorSpace`), sin eso el bloom revienta a blanco.
- **`orb/vendor/`** — terceros vendorizados: Three.js (módulo + postprocessing UnrealBloom + shaders)
  y **`orb/vendor/livekit/livekit-client.esm.mjs`** (SDK JS del cliente LiveKit, modo room).

## `tests/` y `tools/`

- **`tests/test_pure.py`** — unittest de funciones puras: TTS (clean/chunk/flush), keywords de
  sesión, guard denylist, attach consume-once. Es la verificación automatizada del repo.
- **`tools/say.py`** — utilidad TTS suelta (auxiliar, no test).
