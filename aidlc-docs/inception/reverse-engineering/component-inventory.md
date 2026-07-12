# Component Inventory

> El proyecto NO está dividido en "packages" desplegables al estilo cloud/CDK. Es un monolito
> modular Python con **modo ÚNICO room** (LiveKit + transporte WebRTC). Se inventarían los
> componentes lógicos (procesos, módulos, adaptadores) del sistema tal como está en el código.
> El transporte console y el flujo clásico standalone (`VOICE_LIVEKIT`) se ELIMINARON en el
> Ciclo 4 (U7): sus componentes ya NO están inventariados acá.

## Procesos en runtime (modo room, único)

Cuatro procesos cooperantes locales + el cliente en el browser. Los levanta `saga-ctl` (`vcctl.py`).

| Proceso | Responsabilidad | Archivos clave | Interfaces | Depende de |
|---|---|---|---|---|
| **`livekit-server`** (binario nativo) | Server WebRTC: hostea el room `saga`, enruta los tracks de audio entre cliente y worker. NO Docker (el NAT rompía el WebRTC con `dtls timeout`). | `~/.local/bin/livekit-server`, `livekit.yaml` | signaling `127.0.0.1:7880` (loopback) · media UDP `:7882` por IP de LAN (`NODE_IP`) | keys `LIVEKIT_KEYS` (de `.env.local`); relanzado FRESCO en cada `start` |
| **worker / agente** (`lk/agent.py start`) | El cerebro del audio: `AgentSession` dueña de STT/TTS/VAD/turn/LLM. Arma el `AgentServer` con **dispatch AUTOMÁTICO** (U8) y expone el socket de control. | `lk/agent.py`, `lk/claude_llm.py`, `lk/whisper_stt.py`, `lk/edge_tts_plugin.py`, `lk/onnx_tune.py` | socket de control `LK_CTL_SOCK` (`press`/`say`/`stage`); track de audio ↔ room; `orb_state` → orbe | server, `claude_daemon`, orbe; Deepgram (si hay key); Silero VAD |
| **`claude_daemon.py`** (cerebro) | Proceso `claude` caliente (stream-json) que mata el cold-start por turno. Contexto por uuid de `session.json`; `--resume`; respawn si cae. | `claude_daemon.py`, `vc/claudecli.py` | socket Unix `/tmp/saga-claude.sock` (`0o600`) | CLI `claude`; toggle `CLAUDE_PLUGINS`; guard `vc/guard.py` |
| **`orb/orb_server.py`** (orbe) | Server SSE del estado del orbe + endpoint `/token` (JWT del cliente) + puente HTTP→socket (el browser no puede abrir un Unix socket). | `orb/orb_server.py`, `vc/orb.py` | HTTP `127.0.0.1:8777` (`ORB_PORT`): `/token`, `/state`, `/attach`, `/stage`, `/say` | reenvía a `LK_CTL_SOCK`; `livekit.api.AccessToken` |
| **cliente = browser** (efímero) | Render Three.js del orbe. LiveKit JS SDK: pide `/token`, se une al room (esto CREA el room y dispara el dispatch automático), publica el mic (muteado; desmuta en `rec`), reproduce el track TTS y **anima el orbe con el nivel real de la voz** (Web Audio AnalyserNode). | `orb/orb.html`, `orb/vendor/livekit/`, `orb/vendor/three/` | WebRTC ↔ room; SSE + `/token` ↔ orb_server | server, orb_server |

**Trigger de turno** (efímero): Win+Z (Hyprland) → `press` al socket `LK_CTL_SOCK`. Ya NO hay
proceso `saga.py`/`_do_turn` por turno (era del flujo clásico, eliminado).

## Componentes lógicos

### Turn handler
- **`lk/claude_llm.py` (`ClaudeCodeLLM`)** — el ÚNICO turn handler. LLM custom de LiveKit: toma el
  último turno, engancha comandos de voz (reset, visión) reusando helpers de `vc/`
  (`is_reset_command`, `is_visual_command`, `take_staged`), consume adjuntos y delega en
  `claude_daemon` vía `ask_claude_stream`. Al agregar/tocar un comando de voz, se cablea acá.

### STT / TTS (lo decide la presencia de `DEEPGRAM_API_KEY`, NO un flag)
- **Deepgram** (default, si hay key) — STT `deepgram.STT(nova-3, es)` + TTS
  `deepgram.TTS(aura-2-gloria-es)`. Voz en la constante `_DEEPGRAM_VOICE` de `lk/agent.py`.
- **Fallback local** (sin key, DENTRO del agente, sin daemons aparte):
  - **`lk/whisper_stt.py`** — STT faster-whisper; params en fuente única `config.WHISPER_DECODE`
    (`beam>=3` obligatorio para no disparar loops de alucinación).
  - **`lk/edge_tts_plugin.py`** — TTS edge-tts.

### VAD y turn detection
- **Silero VAD** — fin de turno por silencio y barge-in. `turn_detection="vad"` (VAD puro). El
  turn detector semántico `MultilingualModel` fue REEMPLAZADO por VAD puro en **U10** → liberó
  ~1.8 GB de RAM (worker de ~2.6 a ~0.9 GB). Config toda dentro de `turn_handling`
  (`preemptive_generation` apagado, `endpointing min_delay 3.0`, `interruption mode vad`).

### Wake word (opt-in)
- **`WakeWordTrackDetector`** (definido en `lk/wakeword.py`, instanciado por `lk/agent.py`) — wake
  "hey saga" en el worker sobre el track del mic, opt-in con `SAGA_WAKE_ENABLED=1` (default off).
  Corre en ONNX Runtime.
- **`lk/onnx_tune.py`** (U9) — parchea `ort.InferenceSession` (intra/inter=1 + `allow_spinning=0`)
  ANTES de cargar cualquier modelo de audio; mata el ~367% CPU idle del wake. NO sacarlo.
- (`wake_daemon.py` = wake Vosk, DORMIDO, fuera de scope.)

### Seguridad
- **`vc/guard.py`** — hook PreToolUse con denylist de bash catastrófico. Claude corre con
  `--dangerously-skip-permissions` (`VOICE_CLAUDE_SAFE=1` lo apaga); el guard es la red. Fail-open.

### Toggle de stack agéntico
- **`CLAUDE_PLUGINS`** (U11, default `0`) — `=1` carga plugins de Claude en el daemon (MCP + skills
  + hooks + slash), menos los de `configs/plugins-blacklist.json`; off = claude pelado (más rápido).

### Transporte de control
- **`LK_CTL_SOCK`** (socket Unix, perms `0o600`) — canal de control del agente:
  - `press` — Win+Z (push-to-talk).
  - `say` — prompt por texto (Shift+Enter → `/say` → `generate_reply(user_input=text)`).
  - `stage` — texto del panel → staging en MEMORIA del agente (`vc/attach._pending_text`), NO filesystem.

### Endpoints HTTP del orbe (`orb/orb_server.py`, `127.0.0.1:8777`)
- **`/token`** — mintea el JWT del cliente (`livekit.api.AccessToken`, solo `room_join`). NO despacha.
- **`/events`** — stream SSE del estado del orbe (idle/rec/busy/…).
- **`/state`** — POST setter del estado (lo postean los procesos de voz vía `vc/orb.orb_state`).
- **`/attach`** — imagen de visión por dead-drop en `/tmp` (Claude la lee como `screenshot_path`).
- **`/stage`** — texto del panel → reenvía `stage <b64>` al socket → memoria del agente.
- **`/say`** — prompt por texto → reenvía al socket → turno sin audio.

## Orquestación / control plane
- **`vcctl.py` (`saga-ctl`)** — ciclo de vida `start`/`stop`/`status`/`restart`. `_start_room()`
  levanta en orden con readiness por pieza: server fresco → `claude_daemon` (dedup) → orbe (dedup)
  → worker fresco (espera "registered worker") → browser (trigger del dispatch AUTOMÁTICO) → espera
  al `LK_CTL_SOCK` (readiness real del agente). `stop` baja todo (incluido el binario, match por
  basename, sin tocar esta sesión de claude). saga-ctl ya NO despacha por API (U8).

## Soporte reusado (`vc/`, librería interna)
- `config.py` — fuente única de paths, flags, voces, system prompt, regex, args Claude, `WHISPER_DECODE`.
- `claudecli.py` — cliente del cerebro (daemon + one-shot fallback, imagen, sesión).
- `session.py` — sesión uuid + detección de keywords de voz (`is_reset_command`, `is_visual_command`).
- `attach.py` — adjuntos consume-once (texto en memoria / imagen en `/tmp`).
- `desktop.py` — grim (screenshot), monitor kitty, Hyprland.
- `runtime.py` — log rotativo, cancelación, kill de procesos, PID-files anti-recycle.
- `guard.py` — hook de seguridad (arriba).
- `orb.py` — cliente HTTP no bloqueante del orbe.
- `doctor.py` — diagnóstico de entorno (`saga.py --doctor`).
- `sound.py` — genera el beep del wake (`ensure_beep`), lo usa `lk/wakeword.py`. VIVO.
- (Los módulos de audio del flujo clásico —`stt.py`/`tts.py`/`audio.py`— fueron ELIMINADOS en U7;
  el audio lo gobierna LiveKit dentro del agente.)

## Infraestructura
- **Ninguna** (sin CDK/Terraform/CloudFormation). El "deployment" es instalación local:
  `pip install -e .` en venv + wrappers en `~/.local/bin` (`saga-ctl`, `livekit-server`) + keybind
  Hyprland (Win+Z). Estado sin base de datos: `session.json` (uuid) + efímeros en `/tmp` (tmpfs).

## Test / tooling
- **`tests/test_pure.py`** — unit de funciones puras. 3 clases: `TestSessionKeywords` (keywords de
  voz), `TestGuardDenylist` (denylist del guard), `TestAttach` (adjunto consume-once). NO hay tests de
  TTS (se fueron con `vc/tts.py` en U7). CI (`.github/workflows/tests.yml`): `py_compile` de todo el
  repo + `tests.test_pure`, stdlib-only, en cada push/PR a `main`.
- **`tools/measure_stack.py`** — harness de medición de recursos del stack agéntico (RSS/CPU/TTFT, U11).

## Integraciones externas
- **Deepgram** (STT/TTS Nova-3 + Aura-2, nube, si hay key).
- **Microsoft Edge TTS** + **faster-whisper** (fallback local, dentro del agente).
- **Claude Code CLI** (`claude`, el cerebro).
- **Binarios de sistema**: `livekit-server` (WebRTC), `grim` (screenshot), `mpg123`/`pacat`/`paplay`
  (audio), `hyprctl`/`kitty`/`xdg-open` (escritorio).

## Runtime en una línea
`livekit-server` (nativo) · `lk/agent.py start` (worker) · `claude_daemon.py` (cerebro) ·
`orb/orb_server.py` (orbe + `/token`) · cliente en el browser. Ver `pgrep -af
"livekit-server|lk/agent.py|claude_daemon|orb_server"`.
