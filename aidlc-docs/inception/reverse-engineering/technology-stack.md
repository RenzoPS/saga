# Technology Stack

## Programming Languages

- **Python** — 3.12+ (`requires-python = ">=3.12"`, `.python-version` local) — toda la lógica:
  orquestación, worker LiveKit, daemons, integración OS, STT/TTS de fallback, control.
- **JavaScript (ES modules)** — `orb/orb.html` + Three.js vendorizado + LiveKit JS SDK vendorizado
  (`orb/vendor/livekit/`) — render 3D del orbe y cliente WebRTC del room.
- **HTML/CSS** — `orb/orb.html` — superficie del orbe servida por `orb_server.py`.

## Frameworks / Librerías clave

- **LiveKit Agents** (`livekit-agents`, sin pin) — runtime de audio del **modo room** (único, Ciclo 4):
  el worker (`lk/agent.py`) arma un `AgentServer` + `AgentSession` (STT/LLM/TTS/VAD/turn) y se conecta por
  WebRTC al `livekit-server` local. Dueño de captura, streaming, chunks, VAD, fin de turno y barge-in.
  El transporte `console` y el flujo clásico standalone se ELIMINARON (U7).
- **livekit-plugins-silero** — VAD (voz vs silencio): fin de turno por SILENCIO (`turn_detection="vad"`,
  `activation_threshold 0.7`) + barge-in local (`interruption mode "vad"`). Único mecanismo de turnos (U10).
- **livekit-plugins-deepgram** — STT Nova-3 + TTS Aura-2 (streaming, default si hay key).
- **livekit-plugins-turn-detector** — dependencia declarada, pero el EOU semántico (`MultilingualModel`) ya
  **NO se usa**: U10 lo reemplazó por VAD puro → liberó ~1.8 GB de RAM y sacó el error "Error predicting end
  of turn". Los turnos cierran por silencio (silero), no por el sentido de la frase.
- **livekit-plugins-noise-cancellation** — BVC (Krisp) declarado, pero **inhabilitado en room**: requiere
  LiveKit Cloud y falla contra el server self-hosted ("audio filter cannot be enabled"). El room se apoya en
  el VAD Silero para el ruido.
- **livekit-wakeword[listener]** (sin pin) — wake word "hey saga" server-side, **opt-in** (`SAGA_WAKE_ENABLED=1`).
  Corre en el worker sobre el track del mic (`WakeWordTrackDetector`). Su backend es **onnxruntime**, con threads
  capeados por `lk/onnx_tune.py` (U9, ver abajo).
- **faster-whisper** (`==1.2.1`) — STT local de fallback (`lk/whisper_stt.py`), DENTRO del agente cuando no hay
  `DEEPGRAM_API_KEY`. Params de decode en fuente única `config.WHISPER_DECODE` (`beam>=3` para evitar loops).
- **edge-tts** (`==7.2.8`) — TTS neural multilingüe de fallback (`lk/edge_tts_plugin.py`, Microsoft, online, sin key).
- **python-dotenv** (sin pin) — carga `DEEPGRAM_API_KEY` + `LIVEKIT_*` de `.env.local` al importar el módulo.
- **sounddevice** (`==0.5.5`) — captura de mic para el wake_daemon Vosk (dormido) + health-check `vc/doctor.py`.
- **numpy** (`==2.4.6`) — buffers de audio.
- **vosk** (sin pin) — wake word local (`wake_daemon.py`, DORMIDO, fuera de scope).
- **Three.js** (vendorizado en `orb/vendor/`) — render del orbe + postprocessing (UnrealBloom).
- **stdlib only** en `orb_server.py` (http.server, sockets) — sin deps pip para el server del orbe.

## Infraestructura / Servicios

- **livekit-server** (BINARIO NATIVO en `~/.local/bin/`, NO Docker) — server WebRTC local que hostea el room
  `saga`. El NAT de Docker sobre localhost rompía el WebRTC (`dtls timeout`) → se usa el binario nativo. Config
  `livekit.yaml`: signaling en loopback (`:7880`) + `udp_port 7882` para media; `node_ip` = IP de LAN
  auto-detectada (`NODE_IP`, `ip route`), porque LiveKit nunca bindea el UDP de media a loopback. Keys de
  `.env.local` (`LIVEKIT_KEYS`). Dispatch AUTOMÁTICO (U8): el server despacha el worker solo cuando el browser
  crea el room.
- **Deepgram** (nube) — STT Nova-3 (`nova-3`, es) + TTS Aura-2 (`aura-2-gloria-es`). Default cuando hay
  `DEEPGRAM_API_KEY` en `.env.local`. Único servicio cloud de pago. El stack lo decide la PRESENCIA de la key,
  no un flag.
- **Microsoft Edge TTS** (online, sin cuenta) — TTS de fallback.
- **Claude Code CLI** (`claude`) — el cerebro; corre como daemon persistente (`claude_daemon.py`, modo
  stream-json) con fallback a one-shot. **Stack agéntico opt-in** vía `CLAUDE_PLUGINS` (U11): apagado por
  default (system prompt propio, `--setting-sources ''` stripped); prendido habilita plugins/MCPs del harness
  para turnos con herramientas (que tardan 13-17s+ → el watchdog `_busy` se subió a 60s).
- **Sistema operativo / escritorio**: Arch Linux, Hyprland (Wayland). Binarios: `grim` (screenshot),
  `mpg123`/`pacat`/`paplay` (audio), `hyprctl`/`kitty`/`xdg-open` (integración de escritorio).
- **Transporte**: WebRTC (audio del room, browser ↔ server ↔ worker) + sockets Unix (`LK_CTL_SOCK` control del
  agente, cerebro; perms `0o600`) + HTTP loopback (orbe + `/token`, `127.0.0.1:8777`).
- **Almacenamiento**: filesystem local. Estado mínimo (`session.json`) + efímeros en
  `/tmp` (tmpfs/RAM). Sin base de datos.

## Build Tools

- **setuptools** (`>=61`, build-backend `setuptools.build_meta`) — empaquetado (`pyproject.toml`).
- **pip** — instalación (`pip install -e .`) + lock (`requirements.txt` via freeze). `uv` opcional/recomendado
  en el README. Deps sin pin de versión salvo el fallback local (whisper/edge/sounddevice/numpy).
- **venv** (`.venv/`) — entorno aislado. Siempre `.venv/bin/python` (las deps viven en el venv).
- **Entry points**: `saga` (=`vc.app:main`), `saga-ctl` (=`vcctl:main`, orquestador del modo room).

## Testing Tools

- **unittest** (stdlib) — `tests/test_pure.py`. Sin frameworks externos (pytest/hypothesis no usados).
- **py_compile** (stdlib) — smoke check de compilación (`.venv/bin/python -m py_compile lk/*.py vc/*.py …`).
- El flujo de audio/Win+Z NO es runtime-testeable desde el harness (mic, subprocess, threads, signals):
  lo prueba el usuario en vivo. Hay git baseline para rollback.
- **CI**: `.github/workflows/tests.yml` (push/PR a `main`, Python 3.12, stdlib-only) corre `py_compile`
  de todo el repo (`git ls-files '*.py'`) + `unittest tests.test_pure`. Es un smoke, no cobertura.
- No hay coverage, lint config (ruff/flake8) ni type checker (mypy) declarados en el repo.

## Observabilidad

- **Log de archivo** (`saga.log`, rotativo a 512KB, 0o600) — lo tailea el monitor kitty; eventos del flujo
  con prefijo `▎`.
- **Métricas de LiveKit** por etapa (`metrics_collected`: ttft, ttfb, duration, etc.) al log.
- **Log del worker LiveKit** (`livekit_agent.log`).
- **Cap de threads ONNX (U9, `lk/onnx_tune.py`)** — no es observabilidad, pero es tuning de runtime clave:
  `cap_onnx_threads()` (intra/inter=1 + `allow_spinning=0`) baja el CPU idle del wake de ~410% a ~40%. NO sacarlo.
- Sin tracing distribuido ni métricas exportadas (no aplica: app de escritorio single-user).
