# Guía del código (archivo por archivo)

Qué hace cada módulo y cómo encaja. Para el detalle a nivel función, los **docstrings del código
son densos y confiables** — leelos en el archivo.

## Raíz (entrypoints y daemons)

- **`saga.py`** — entrypoint fino de Win+Z. Delega en `vc.app.main`: emite el `press` al socket de
  control del agente (y expone `--doctor`). Es lo que llama el wrapper de Hyprland.
- **`vcctl.py`** (`saga-ctl`) — control del ciclo de vida: `start/stop/status/restart`. Mata por
  **basename/ruta exacta** leyendo `/proc` (nunca `pkill -f`, que se auto-mataría y pegaría en el
  `claude` CLI). **`_start_room()`** (único modo, Ciclo 4) orquesta server fresco → cerebro → orbe →
  worker fresco → browser → wait del socket de control, con readiness por pieza. El server y el worker se
  relanzan FRESCOS en cada `start` (helper `_kill_pids` baja los viejos; claude_daemon y orbe se reusan si ya
  corren). El dispatch del worker es AUTOMÁTICO (lo dispara el browser al unirse al room) → ya no hay paso de
  dispatch por API. Helpers room: `_node_ip()` (IP LAN primaria por socket UDP, sin subprocess),
  `_livekit_server_pids()` (match basename `livekit-server`). `stop` baja todo, incluido el binario nativo.
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
  llega por el track del browser. Construye el server `AgentServer(load_fnc=lambda: 0.0, drain_timeout=0,
  num_idle_processes=1)`. El **dispatch lo pide `orb_server` por API** (`vc/dispatch.py`) desde `/token`,
  cuando el cliente está por entrar: ni automático (despacha al crearse el room, y el cliente le ganaba
  ~2s al registro del worker) ni por token (`JT_PARTICIPANT`, que el SDK de Python no sabe atender).
  `load_fnc=0` → nunca se auto-marca
  `unavailable` (era la causa raíz del Win+Z `FileNotFoundError` intermitente: el prod `load_threshold=0.7`
  shedeaba bajo la carga de arranque). `drain_timeout=0` → SIGTERM cierra al toque (libera el :8081).
  `num_idle_processes=1` → un solo proceso forkeado (saga atiende 1 turno a la vez). Hace
  `os.environ.pop("LIVEKIT_AGENT_NAME", None)` antes de crear el server (si esa env existiera, el SDK forzaría
  explicit dispatch). `session.start(..., room_options=RoomOptions(close_on_disconnect=False))` →
  recargar/cerrar la pestaña del orbe NO mata la sesión ni el socket de Win+Z. (`RoomInputOptions`/
  `RoomOutputOptions` están deprecados y mueren en v2.0.) Arma el `AgentSession` (STT+VAD+LLM+TTS) con
  TODA la config de turnos dentro de `turn_handling`, que **ramifica por modo** (`_turn_handling()`):
  en llamada `turn_detection="stt"` (lo decide Flux) y sin `endpointing`; en push-to-talk
  `turn_detection="vad"` (silero; U10 sacó el `MultilingualModel` semántico → −1.8 GB de RAM) con
  `endpointing` min 1.2s / max 6s. La `interruption` es común a los dos: `mode="vad"` (el `adaptive`
  necesita LiveKit Cloud), `min_words=2`, `min_duration=0.5`, `resume_false_interruption` con
  `false_interruption_timeout=1.5`. `preemptive_generation` **OFF** en ambos (sobre transcripts
  parciales rompía el LLM bloqueante; la especulación que queremos es el `eager_eot` de Flux).
  El `atexit` que limpia el socket de control se registra **dentro de `entry()`** y compara inodo —a
  nivel de módulo se lo llevaban los procesos prewarm de LiveKit, dejando la llamada viva sin poder
  colgar. Implementa las fases de Win+Z (`_press`: 3 fases en ptt, abrir/colgar en llamada, con el
  timer `_arm_call_idle` de 180s), el prompt por texto (`_say`), el socket de control
  (`press`/`stage`/`say`), y los handlers de estado `_on_agent_state`/`_on_user_state`. **Timers
  propios** (`asyncio.call_later`, sin internals): `_arm_away` (6s "abriste el mic y no hablaste",
  VAD-aware) y `_arm_busy` (60s watchdog de turno colgado en thinking; era 18s, subido en
  Ciclo 5 porque los turnos con tool/MCP tardan 13-17s+). BVC (noise cancellation) NO
  se usa: requiere LiveKit Cloud → falla en el server self-hosted; room se apoya en el VAD Silero.
  Además levanta orbe + precalienta Claude (dedup-safe). Plugins LiveKit importados a **nivel
  módulo** (deben registrarse en el main thread).
- **`lk/claude_llm.py`** — LLM custom de LiveKit = **el ÚNICO turn handler**. Reenvía el
  último turno del usuario a `claude_daemon`, engancha comandos de voz (reset, visión), consume
  adjuntos staged, y puentea el generador bloqueante de Claude a deltas asyncio. Cancelación en
  barge-in: al cancelar LiveKit el turno, setea el flag `_cancel` (que `claudecli`/daemon respetan)
  y espera al worker antes de limpiarlo.
  Ojo con un detalle del orden: el detector de visión corre sobre `pedido` (lo que dijiste vos),
  **no** sobre el `prompt` final. Corría sobre el compuesto y la nota de `heard` citaba a Claude:
  contando sobre "San Nicolás de **Mira**" disparaba capturas de pantalla que nadie pidió.
- **`lk/speech.py`** — voz del **turno segmentado** y su concurrencia. El primer bloque lo habla el
  pipeline normal; los siguientes, `session.say()` (primitiva nativa: no sintetizamos audio). Cada
  bloque abre y cierra su propio websocket, así el hueco de tools no cruza ninguno abierto. Numera los
  turnos (`new_turn()`) para que uno viejo no pise al vigente, y cancela **las dos puntas**: el task
  async y el thread bloqueado en el socket del daemon, con un `threading.Event` **por turno**.
- **`lk/heard.py`** — qué llegaste a **escuchar** de una respuesta cortada. LiveKit trunca y marca
  `ChatMessage.interrupted`; el módulo lee ese texto y lo deja como nota consume-once para el próximo
  prompt. No reimplementa la truncación: la transporta al lado de Claude, que cree que dijo todo.
- **`lk/wakeword.py`** — detector "hey saga" sobre el track del mic del browser. Usa el
  `WakeWordModel` oficial de `livekit.wakeword`, pero la ventana deslizante es propia: el
  `WakeWordListener` nativo lee portaudio (mic local) y no acepta un track.
- **`lk/onnx_tune.py`** — capea threads de ONNX **antes** de instanciar cualquier `InferenceSession`.
- **`lk/whisper_stt.py`** — adaptador STT faster-whisper para LiveKit (fallback sin Deepgram).
- **`lk/edge_tts_plugin.py`** — plugin TTS edge-tts para LiveKit (fallback sin Deepgram).

## `vc/` — soporte (reusado por ambos modos)

- **`vc/config.py`** — **fuente única** de paths, flags, voces, system prompt (agéntico: usa las
  tools built-in tipo Bash), regex (reset/visual), y los args base de `claude`
  (`build_claude_base_args`, compartidos por daemon y one-shot). **Carga `.env.local` al importar**
  (idempotente) para que cualquier importador —incluido `orb_server`, que mintea el JWT— vea las
  keys. Constantes del modo room (Ciclo 4): `LIVEKIT_URL/API_KEY/API_SECRET/ROOM`,
  `LIVEKIT_SERVER_BIN`/`LIVEKIT_CONFIG`/`LK_SERVER_LOG`, `LIVEKIT_SIGNAL_PORT` (7880). (La constante
  `LIVEKIT_AGENT_NAME` se ELIMINÓ en U8: el dispatch es automático, sin agente nombrado.) Las keys solo
  viven en `.env.local`; URL/room tienen default local. **Toggle de plugins (Ciclo 5)**: `CLAUDE_PLUGINS`
  decide los flags del daemon — off (default) = claude pelado (`--setting-sources '' --disable-slash-commands`);
  on = carga los plugins menos la blacklist (`configs/plugins-blacklist.json` → `enabledPlugins:false` por plugin,
  aislado en `.saga-settings.json`, sin tocar `~/.claude`).
- **`vc/claudecli.py`** — cliente de Claude con dos caminos: daemon (rápido) + fallback one-shot
  (`claude -p`). Maneja imagen (multimodal por stdin), reintento de sesión, y respeta el flag global
  de cancelación.
- **`vc/session.py`** — sesión uuid persistida (escritura atómica) + detección de keywords:
  `is_reset_command`, `is_visual_command`. **No hay timeout**: la sesión persiste entre reinicios de
  saga hasta que pidas un reset por voz, así que `saga-ctl start` siempre reanuda (`--resume`) y nunca
  arranca de cero. Medido: 823 mensajes / 816 KB tras un día de uso, y recargar eso cuesta ~1.4s.
- **`vc/dispatch.py`** — `ensure_agent()`: le pide a LiveKit que meta al worker en la sala, por API,
  desde `/token`. Idempotente (no duplica agentes) y **nunca rompe el pedido del cliente**: si el
  dispatch falla, el token sale igual. El módulo documenta por qué no se usa el dispatch automático
  ni el firmado en el JWT.
- **`vc/attach.py`** — adjuntos del panel, **consume-once**: texto en memoria del proceso agente,
  imagen como path en `/tmp`. `take_staged()` consume en el turno.
- **`vc/desktop.py`** — integración Hyprland: `grim` (screenshot), monitor kitty con tail del log.
- **`vc/runtime.py`** — estado runtime compartido (evita ciclos de import): log rotativo (512KB),
  evento de cancelación, kill de proceso/streamer por grupo, **PID-files anti-recycle** (validan
  `starttime` de `/proc` para que un PID reciclado no se haga pasar por el dueño).
- **`vc/guard.py`** — hook **PreToolUse** de Claude: denylist de bash catastrófico (rm -rf, dd,
  mkfs, fork bomb, git reset --hard, sobrescribir dotfiles…). Fail-open. Función pura `denied()` testeable.
  Se inyecta vía `.saga-settings.json` (settings aditivo per-sesión del daemon, que además lleva el
  `enabledPlugins:false` de la blacklist cuando `CLAUDE_PLUGINS=1`).
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
  (`livekit.api.AccessToken`, SOLO para unirse; el dispatch del worker es AUTOMÁTICO del server cuando el
  browser entra al room, no lo hace el token ni una llamada API); `livekit.api` se importa **lazy** dentro del handler. Sirve
  el vendor con MIME para `.mjs` (módulos ES). Watchdog que vuelve a idle si saga muere.
- **`orb/orb.html`** — render Three.js del orbe (estados acoplados por bloom) **+ cliente LiveKit**
  (Ciclo 4): pide `/token`, se une al room (`Room.connect`), publica el mic muteado (desmutea en
  `rec` vía el estado SSE) y recibe el track TTS. Con **Web Audio `AnalyserNode` sobre ese track
  (U5)** el orbe late con el nivel REAL de la voz (`window.__ttsLevel()`). Cuidado: colores de fondo
  en **sRGB** (`THREE.SRGBColorSpace`), sin eso el bloom revienta a blanco.
  - **Gate del mic por estado**: `rec` → unmute, cualquier otro → mute. Con `SAGA_WAKE_ENABLED=1` el
    gate **no aplica** y el mic queda desmuteado siempre (el server necesita oír "hey saga"). Ojo:
    en modo llamada el estado es `listen`, no `rec` → hoy el mic solo queda abierto **porque el wake
    está ON**. Ver D13 en [`tech-debt-plan.md`](tech-debt-plan.md).
  - **Control de micrófono** (arriba a la izquierda, espejo de `#conn`): mute con clic o tecla `M`, y
    selector de dispositivo. Sobre el SDK pelado —sin `@livekit/components-react`— con las tres
    primitivas que envuelven sus hooks: `micTrack.mute()/unmute()`, `Room.getLocalDevices('audioinput')`
    y `room.switchActiveDevice(...)`. Dos detalles no obvios, copiados del starter oficial: los devices
    llegan con `deviceId` **vacío** hasta que se concede el permiso (por eso se filtran, y por eso el
    control aparece recién con el track ya publicado), y el **mute manual tiene que ganarle** al gate
    automático o el próximo cambio de estado te desmutea solo.
  - **Un solo `<audio>` por track**: `attachRemoteAudio` limpia el anterior. Antes solo appendeaba y,
    con `close_on_disconnect=False`, cada `saga-ctl restart` sumaba otro elemento sobre el MISMO track
    → dos pipelines de playback con jitter buffers independientes → interferencia destructiva. No
    suena a eco: suena a que el volumen se desplomó de la nada.
- **`orb/vendor/`** — terceros vendorizados: Three.js (módulo + postprocessing UnrealBloom + shaders)
  y **`orb/vendor/livekit/livekit-client.esm.mjs`** (SDK JS del cliente LiveKit, modo room).

## `tests/` y `tools/`

- **`tests/test_pure.py`** — unittest de funciones puras (3 clases): keywords de sesión
  (`TestSessionKeywords`), guard denylist (`TestGuardDenylist`), attach consume-once (`TestAttach`).
  Es la verificación automatizada del repo (la corre el CI en `.github/workflows/tests.yml`).
- **`tools/measure_stack.py`** — harness de medición de recursos del stack agéntico (RSS/CPU/TTFT, U11).
