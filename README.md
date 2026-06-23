# saga

Asistente de voz para Linux/Hyprland: **voz → Claude Code → voz**, sobre **LiveKit**
(runtime de audio) + **Deepgram** (STT/TTS), con un orbe 3D que reacciona al estado.
Push-to-talk con Win+Z.

Por default corre en **modo room**: un server LiveKit local (binario nativo) + el browser
como cliente (orbe) que publica el mic y reproduce el TTS + un worker (el cerebro). Hay
fallbacks: transporte `console` (audio local, sin server) y flujo clásico (whisper/edge).

## Flujo

```
Win+Z → browser publica el mic → server LiveKit local (WebRTC)
        → worker: LiveKit (streaming, VAD, turn semántico, barge-in)
        → Deepgram Nova-3 (STT streaming)
        → Claude Code (daemon caliente, el cerebro: responde y hace cosas en la compu)
        → Deepgram Aura-2 (TTS, voz es. gloria)
        → browser reproduce el TTS y el orbe late con la voz real (Web Audio)
```

**LiveKit es dueño de todo el runtime de audio** (captura, chunks, streaming, detección
de fin de turno, barge-in). Nosotros enchufamos las piezas: STT, cerebro y TTS. El cerebro
es **Claude Code** (no una API plana) → puede ejecutar bash, leer archivos, usar MCP: hace
cosas en la máquina, no solo conversa.

### Latencias típicas (con Deepgram)
STT ~0.3s · Claude TTFT ~2s · TTS ttfb ~0.3s → **~2-3s de "callaste" a "te habla"**.

## Documentación

Documentación para mantenedores en [`docs/`](docs/): [arquitectura](docs/architecture.md) ·
[flujo de un turno](docs/turn-flow.md) · [API interna](docs/internal-api.md) ·
[guía del código](docs/code-guide.md) · [operación](docs/operations.md) ·
[deuda técnica + plan](docs/tech-debt-plan.md). Empezá por [`docs/README.md`](docs/README.md).

## Requisitos

- Python 3.12 + venv del proyecto (`.venv/`).
- **`livekit-server`** (binario nativo) en `~/.local/bin/` — el modo room corre un server
  LiveKit local (no Docker; el NAT de Docker rompe el WebRTC sobre localhost).
- **`DEEPGRAM_API_KEY`** + **`LIVEKIT_API_KEY`/`LIVEKIT_API_SECRET`** en `.env.local`
  (gitignored). Sin la key de Deepgram, cae a fallback local (faster-whisper + edge-tts).
- Binarios: `claude` (CLI), `mpg123`, `grim` (screenshot), `hyprctl`/`kitty`/`xdg-open`,
  y un browser (el cliente del orbe).
- Hotkey: bind de Hyprland a `~/.local/bin/saga` (Win+Z).

## Setup (desde cero)

**1. Binarios del sistema** (Arch):
```bash
sudo pacman -S mpg123 grim kitty        # reproducción / screenshot / monitor
# claude CLI:  https://github.com/anthropics/claude-code   (npm i -g @anthropic-ai/claude-code)
# uv (opcional, recomendado):  https://docs.astral.sh/uv/
```

**2. Crear el venv e instalar el proyecto** (genera los comandos `saga` y `saga-ctl` en `.venv/bin/`):
```bash
python -m venv .venv                                  # o: uv venv
.venv/bin/python -m pip install -e .                  # o: uv pip install --python .venv/bin/python -e .
```

**3. El server LiveKit nativo** (binario, NO Docker — el NAT de Docker rompe el WebRTC local):
```bash
# Release oficial de livekit/livekit a ~/.local/bin/livekit-server.
# El instalador oficial baja el binario para tu plataforma:
curl -sSL https://get.livekit.io | bash                # deja livekit-server en el PATH
# Movelo/symlinkealo a ~/.local/bin/ si no quedó ahí (es donde lo busca saga-ctl):
#   install -Dm755 "$(command -v livekit-server)" ~/.local/bin/livekit-server
```
> La config vive en `livekit.yaml` (versionada, sin secretos): signaling en loopback
> (`:7880`), media UDP en `:7882`. `saga-ctl` auto-detecta la IP de LAN (`NODE_IP`, vía
> `ip route`) e inyecta las keys por env al arrancar — el yaml no las contiene.

**4. Las keys** (gitignored, NO se commitean) en `.env.local`:
```bash
# Deepgram (cuenta free en deepgram.com):
echo 'DEEPGRAM_API_KEY=tu_key' >> .env.local
# LiveKit: generá un par api-key / api-secret con el propio binario:
livekit-server generate-keys                           # imprime un KEY y un SECRET
cat >> .env.local <<'EOF'
LIVEKIT_URL=ws://127.0.0.1:7880
LIVEKIT_ROOM=saga
LIVEKIT_API_KEY=APIxxxxxxxx
LIVEKIT_API_SECRET=secretoxxxxxxxx
EOF
```
Sin la key de Deepgram, cae a fallback local (faster-whisper + edge-tts, más lento).
Sin las keys de LiveKit, el modo room no arranca (usá `SAGA_TRANSPORT=console`).

**5. Comandos globales** (wrappers en `~/.local/bin`, para no activar el venv a mano).
El keybind de Hyprland los necesita por ruta absoluta:
```bash
cat > ~/.local/bin/saga <<'EOF'
#!/usr/bin/env bash
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin"
exec "$HOME/.local/share/saga/.venv/bin/python" "$HOME/.local/share/saga/saga.py" "$@"
EOF
cat > ~/.local/bin/saga-ctl <<'EOF'
#!/usr/bin/env bash
exec "$HOME/.local/share/saga/.venv/bin/python" "$HOME/.local/share/saga/vcctl.py" "$@"
EOF
chmod +x ~/.local/bin/saga ~/.local/bin/saga-ctl
```

**6. Keybind de Hyprland** (Win+Z = push-to-talk). En `~/.config/hypr/.../Keybinds.conf`:
```
bindd = $mainMod, Z, Saga (toggle), exec, /home/TU_USUARIO/.local/bin/saga
```
Después `hyprctl reload`.

> Wake word "saga"/"hey saga": OFF por default (`VOICE_WAKE_ENABLED=1` para activar; requiere el modelo Vosk en `models/`). El trigger normal es Win+Z.

## Correr

```bash
saga-ctl start      # levanta TODO: server nativo + Claude + orbe + worker + dispatch + browser
saga-ctl status     # ver modo, stack (Deepgram vs fallback) y procesos (server/worker/daemon/orbe)
saga-ctl stop       # apagar todo (incluido el binario del server)
```

`saga-ctl start` arranca las piezas en orden con readiness por pieza: el server LiveKit
nativo, el cerebro (`claude_daemon`), el orbe (`orb_server`), el worker (`lk/agent.py
start`), despacha el agente al room por API y abre el browser cliente.

### Uso (Win+Z, push-to-talk de 3 fases)
- **idle → Win+Z**: empieza a grabar (orbe "Grabando").
- **grabando → Win+Z**: corta y manda el turno (o esperá ~2s de silencio, manda solo).
- **procesando/hablando → Win+Z**: mata la respuesta en curso (orbe "Cancelado").
- **Visión on-demand**: decí "mirá la pantalla", "fijate esto", "qué ves" → captura con
  grim, se la manda a Claude, y la borra (privacidad).

## Stack

| Pieza | Tecnología | Notas |
|-------|-----------|-------|
| Transporte | **server LiveKit nativo** (room, local) ↔ browser cliente ↔ worker | default; sin Docker |
| Runtime audio | **LiveKit Agents** (worker `lk/agent.py start`) | captura/stream/VAD/turn/barge-in |
| Turn detection | **MultilingualModel** (EOU semántico) + Silero VAD | anti-chopping de turnos |
| STT | **Deepgram Nova-3** (streaming) | fallback: faster-whisper local |
| Cerebro | **Claude Code** (`claude_daemon`, stream-json) | ejecuta tools/bash/MCP |
| TTS | **Deepgram Aura-2** (voz `aura-2-gloria-es`) | fallback: edge-tts |
| Cliente / orbe | browser con LiveKit JS SDK + Three.js (`orb/orb.html`) | publica mic, late con la voz real (Web Audio) |

## Variables de entorno

El stack se decide **solo** (Deepgram si hay key, fallback si no) — NO hay flags para
elegir proveedor.

Secretos en `.env.local` (gitignored): `DEEPGRAM_API_KEY` · `LIVEKIT_API_KEY` ·
`LIVEKIT_API_SECRET`. También viven ahí `LIVEKIT_URL` (default `ws://127.0.0.1:7880`) y
`LIVEKIT_ROOM` (default `saga`).

Toggles:

| Var | Default | Qué hace |
|-----|---------|----------|
| `SAGA_TRANSPORT` | `room` | `=console` corre el worker con audio local (sin server ni browser) |
| `VOICE_LIVEKIT` | `1` (on) | `=0` vuelve al flujo clásico (Win+Z por-turno, whisper/edge) |
| `VOICE_CLAUDE_SAFE` | (off) | `=1` desactiva `--dangerously-skip-permissions` |
| `VOICE_CLAUDE_MEM` | `0` (off) | `=1` activa claude-mem en voz (+2-7s/turno; respawnear daemon) |
| `ORB_PORT` | `8777` | puerto del server del orbe |

## Arquitectura

Modo room (default) — topología **server LiveKit ↔ browser cliente (orbe) ↔ worker**, todo local:

- **Server**: `livekit-server` nativo (`~/.local/bin/`), config `livekit.yaml`. Signaling en
  loopback (`:7880`), media UDP en `:7882`. `saga-ctl` auto-detecta `NODE_IP` (IP de LAN) e
  inyecta las keys (`LIVEKIT_KEYS`) por env. No Docker: el NAT rompe el WebRTC local.
- **Cliente** (`orb/orb.html`): browser con el LiveKit JS SDK (vendoreado en
  `orb/vendor/livekit/`). Pide el JWT a `/token`, se une al room, publica el mic (muteado;
  desmutea al grabar), recibe el track TTS y lo reproduce; el orbe late con el nivel real
  de la voz (Web Audio `AnalyserNode`).
- **Token + dispatch**: `orb/orb_server.py` `/token` mintea el JWT; `saga-ctl` despacha el
  agente al room por API (`AgentDispatchService.create_dispatch`) → el agente entra ANTES
  que el browser (robusto contra timing/pestañas zombie).

Paquete `lk/` (worker):

| Módulo | Responsabilidad |
|--------|-----------------|
| `lk/agent.py` | entrypoint: `lk/agent.py start` (worker room) / `console` (fallback); arma `AgentSession`, 3 fases Win+Z, socket de control |
| `lk/claude_llm.py` | LLM custom de LiveKit que delega en `claude_daemon` (+ visión grim) |
| `lk/whisper_stt.py` | STT de fallback (faster-whisper) si no hay Deepgram |
| `lk/edge_tts_plugin.py` | TTS de fallback (edge-tts) si no hay Deepgram |

Soporte (paquete `vc/`, reusado): `config` (paths/flags/secretos) · `claudecli` +
`claude_daemon.py` (cerebro caliente) · `orb` + `orb/orb_server.py` (orbe + `/token`) ·
`desktop` (grim/Hyprland) · `runtime` · `session`. El flujo clásico (`vc/app.py`,
`whisper_daemon.py`, wake `Vosk`) queda como fallback (`VOICE_LIVEKIT=0`).

Control: `vcctl.py` (`saga-ctl`) orquesta el arranque (`_start_room`: server → daemon →
orbe → worker → dispatch → browser), abre el monitor y espera readiness por pieza. Win+Z
(`vc/app.py` → `_livekit_toggle`) le manda `press` al socket del agente.

## Privacidad

En modo Deepgram, el audio del mic viaja a Deepgram en streaming (precio de la
velocidad). El server LiveKit es local y su signaling bindea solo a loopback (nadie
externo pide token ni se une). Las keys viven en `.env.local` (gitignored). Las capturas
de pantalla se borran inmediatamente tras mandarlas a Claude. Para todo-local
(STT/TTS sin Deepgram): `VOICE_LIVEKIT=0`.
