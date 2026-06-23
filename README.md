# saga

Asistente de voz para Linux/Hyprland: **voz → Claude Code → voz**, sobre **LiveKit**
(runtime de audio) + **Deepgram** (STT/TTS), con un orbe 3D que reacciona al estado.
Push-to-talk con Win+Z.

## Flujo

```
Win+Z → LiveKit (mic, streaming, VAD, turn, barge-in, BVC noise-cancel)
        → Deepgram Nova-3 (STT streaming)
        → Claude Code (daemon caliente, el cerebro: responde y hace cosas en la compu)
        → Deepgram Aura-2 (TTS, voz es. gloria)
        → parlante
        (el orbe sigue cada fase por un socket de control)
```

**LiveKit es dueño de todo el runtime de audio** (captura, chunks, streaming, detección
de fin de turno, barge-in, cancelación de ruido). Nosotros enchufamos las piezas: STT,
cerebro y TTS. El cerebro es **Claude Code** (no una API plana) → puede ejecutar bash,
leer archivos, usar MCP: hace cosas en la máquina, no solo conversa.

### Latencias típicas (con Deepgram)
STT ~0.3s · Claude TTFT ~2s · TTS ttfb ~0.3s → **~2-3s de "callaste" a "te habla"**.

## Documentación

Documentación para mantenedores en [`docs/`](docs/): [arquitectura](docs/architecture.md) ·
[flujo de un turno](docs/turn-flow.md) · [API interna](docs/internal-api.md) ·
[guía del código](docs/code-guide.md) · [operación](docs/operations.md) ·
[deuda técnica + plan](docs/tech-debt-plan.md). Empezá por [`docs/README.md`](docs/README.md).

## Requisitos

- Python 3.12 + venv del proyecto (`.venv/`).
- **`DEEPGRAM_API_KEY`** en `.env.local` (cuenta free de deepgram.com; gitignored).
  Sin la key, cae solo a fallback local (faster-whisper + edge-tts, más lento).
- Binarios: `claude` (CLI), `mpg123`, `grim` (screenshot), `hyprctl`/`kitty`/`xdg-open`.
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

**3. La key de Deepgram** (gitignored, NO se commitea):
```bash
echo 'DEEPGRAM_API_KEY=tu_key' > .env.local           # cuenta free en deepgram.com
```
Sin key, cae solo a fallback local (faster-whisper + edge-tts, más lento).

**4. Comandos globales** (wrappers en `~/.local/bin`, para no activar el venv a mano).
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

**5. Keybind de Hyprland** (Win+Z = push-to-talk). En `~/.config/hypr/.../Keybinds.conf`:
```
bindd = $mainMod, Z, Saga (toggle), exec, /home/TU_USUARIO/.local/bin/saga
```
Después `hyprctl reload`.

> Wake word "saga"/"hey saga": OFF por default (`VOICE_WAKE_ENABLED=1` para activar; requiere el modelo Vosk en `models/`). El trigger normal es Win+Z.

## Correr

```bash
saga-ctl start      # levanta el agente LiveKit + Claude + orbe + monitor
saga-ctl status     # ver modo, stack (Deepgram vs fallback) y daemons
saga-ctl stop       # apagar todo
```

### Uso (Win+Z, push-to-talk de 3 fases)
- **idle → Win+Z**: empieza a grabar (orbe "Grabando").
- **grabando → Win+Z**: corta y manda el turno (o esperá ~2s de silencio, manda solo).
- **procesando/hablando → Win+Z**: mata la respuesta en curso (orbe "Cancelado").
- **Visión on-demand**: decí "mirá la pantalla", "fijate esto", "qué ves" → captura con
  grim, se la manda a Claude, y la borra (privacidad).

## Stack

| Pieza | Tecnología | Notas |
|-------|-----------|-------|
| Runtime audio | **LiveKit Agents** (modo `console`, local, sin servidor) | captura/stream/VAD/turn/barge-in |
| Cancelación ruido | **BVC** (Krisp, `livekit-plugins-noise-cancellation`) | saca guitarra/voces de fondo |
| STT | **Deepgram Nova-3** (streaming) | fallback: faster-whisper local |
| Cerebro | **Claude Code** (`claude_daemon`, stream-json) | ejecuta tools/bash/MCP |
| TTS | **Deepgram Aura-2** (voz `aura-2-gloria-es`) | fallback: edge-tts |
| Orbe | server SSE + Three.js, manejado por socket de control | identidad visual |

## Variables de entorno

El stack se decide **solo** (Deepgram si hay key, fallback si no) — NO hay flags para
elegir proveedor. Los únicos toggles:

| Var | Default | Qué hace |
|-----|---------|----------|
| `VOICE_LIVEKIT` | `1` (on) | `=0` vuelve al flujo clásico (Win+Z por-turno, whisper/edge) |
| `VOICE_CLAUDE_SAFE` | (off) | `=1` desactiva `--dangerously-skip-permissions` |
| `VOICE_CLAUDE_MEM` | `0` (off) | `=1` activa claude-mem en voz (+2-7s/turno; respawnear daemon) |
| `ORB_PORT` | `8777` | puerto del server del orbe |

## Arquitectura

Modo LiveKit (default) — paquete `lk/`:

| Módulo | Responsabilidad |
|--------|-----------------|
| `lk/agent.py` | entrypoint: arma `AgentSession`, 3 fases Win+Z, socket de control, orbe |
| `lk/claude_llm.py` | LLM custom de LiveKit que delega en `claude_daemon` (+ visión grim) |
| `lk/whisper_stt.py` | STT de fallback (faster-whisper) si no hay Deepgram |
| `lk/edge_tts_plugin.py` | TTS de fallback (edge-tts) si no hay Deepgram |

Soporte (paquete `vc/`, reusado): `config` (paths/flags/secretos) · `claudecli` +
`claude_daemon.py` (cerebro caliente) · `orb` + `orb/orb_server.py` (orbe) ·
`desktop` (grim/Hyprland) · `runtime` · `session`. El flujo clásico (`vc/app.py`,
`whisper_daemon.py`, wake `Vosk`) queda como fallback (`VOICE_LIVEKIT=0`).

Control: `vcctl.py` (`saga-ctl`) lanza el agente, abre el monitor y espera readiness.
Win+Z (`vc/app.py` → `_livekit_toggle`) le manda `press` al socket del agente.

## Privacidad

En modo Deepgram, el audio del mic viaja a Deepgram en streaming (precio de la
velocidad). La key vive en `.env.local` (gitignored). Las capturas de pantalla se
borran inmediatamente tras mandarlas a Claude. Para todo-local: `VOICE_LIVEKIT=0`.
