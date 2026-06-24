# Operación

Cómo prender, apagar, observar y diagnosticar saga. Para el detalle del stack LiveKit/Deepgram, ver `lk/README.md`.

## Ciclo de vida (`saga-ctl`)

```bash
saga-ctl start      # levanta server nativo + Claude + orbe + worker + dispatch + browser + monitor
saga-ctl status     # stack (Deepgram vs fallback), server, worker, daemons, readiness
saga-ctl stop       # apaga todo (incluido el binario livekit-server) + limpia sockets/tmp
saga-ctl restart    # stop + start
```

`saga-ctl` es `vcctl.py` (wrapper en `~/.local/bin/saga-ctl`). `start` levanta las piezas del modo room
(único modo) en orden con readiness por pieza:

1. `livekit-server` (binario nativo, `~/.local/bin/`) con `NODE_IP` auto-detectada y `LIVEKIT_KEYS` de `.env.local`.
2. `claude_daemon` (cerebro caliente) — `prewarm_claude()`, dedup-safe.
3. `orb_server` (orbe + endpoint `/token`) — `ensure_orb()`, dedup-safe.
4. worker `lk/agent.py start` — se espera "registered worker" en el log ANTES de seguir.
5. dispatch explícito del agente al room por API (`create_dispatch`, borra huérfanos + crea fresco).
6. abre el browser cliente (`xdg-open` al orbe).

Siempre con el venv del proyecto: `.venv/bin/python`.

```bash
.venv/bin/python lk/agent.py start     # worker en modo room (lo lanza saga-ctl; rara vez a mano)
```

## Uso (Win+Z, push-to-talk)

- **idle → Win+Z**: graba.
- **rec → Win+Z** (o ~2s de silencio): corta y manda el turno.
- **busy → Win+Z**: mata la respuesta en curso.
- **Visión**: decí "mirá la pantalla" / "qué ves" → captura con grim, se la manda a Claude, y la borra.

Ver `turn-flow.md` para el detalle.

## Procesos

**Modo room (único):** `livekit-server` (binario nativo) · `lk/agent.py start` (worker) ·
`claude_daemon.py` (cerebro) · `orb/orb_server.py` (orbe + `/token`). El cliente vive en el browser.

Ver procesos:
```bash
pgrep -af "livekit-server|lk/agent.py|claude_daemon|orb_server"
```

## Logs y monitor

- **`saga.log`** — log principal (eventos del flujo con prefijo ▎ + métricas; rotativo a 512KB → `.log.old`,
  perms 0o600 porque tiene transcripciones).
- **`livekit_server.log`** — stdout/stderr del binario `livekit-server` (modo room).
- **`livekit_agent.log`** — stdout/stderr del worker/agente LiveKit (acá sale "registered worker" y los crashes).
- **Monitor** — `saga-ctl start` abre una ventana kitty (workspace 10) con `tail -F saga.log`.

```bash
tail -F saga.log
```

## Variables de entorno

| Var | Default | Qué hace |
|-----|---------|----------|
| `VOICE_CLAUDE_SAFE` | (off) | `=1` desactiva `--dangerously-skip-permissions` |
| `VOICE_CLAUDE_MEM` | `0` | `=1` activa claude-mem en voz (+2-7s/turno; respawnear daemon) |
| `SAGA_WAKE_ENABLED` | `0` | `=1` activa el wake "hey saga" server-side en el agente |
| `ORB_PORT` | `8777` | puerto del server del orbe |

El stack STT/TTS **no es env**: lo decide la presencia de `DEEPGRAM_API_KEY` en `.env.local`.

## Diagnóstico

```bash
.venv/bin/python saga.py --doctor    # binarios, deps, daemons, config
```

Binarios requeridos: `claude` (crítico), `mpg123`/`pacat`/`paplay` (audio), `grim` (screenshot),
`hyprctl`/`kitty`/`xdg-open` (escritorio). En modo room además: `livekit-server` en `~/.local/bin/`.

## Troubleshooting (modo room)

- **`saga-ctl start` dice "NO existe el binario livekit-server"** → bajá el release oficial de
  `livekit/livekit` a `~/.local/bin/` (es requisito del único modo room).
- **"faltan LIVEKIT_API_KEY/SECRET"** → completá `.env.local` (`LIVEKIT_API_KEY/SECRET` + `LIVEKIT_URL/ROOM`).
- **El server no levanta a tiempo** (`livekit-server NO levantó`) → mirá `livekit_server.log`. Chequeá que el
  puerto de signaling no esté ocupado y que `NODE_IP` resuelva a la IP de LAN real (LiveKit no bindea el UDP de
  media a loopback).
- **"worker NO arrancó" / no aparece "registered worker"** → mirá `livekit_agent.log` (crash de import de
  plugins, falta de deps en el venv, etc.).
- **Win+Z falla con `FileNotFoundError` (socket de control)** → el agente no entró al room (dispatch huérfano
  o pestaña zombie que creó el room antes del worker). `saga-ctl restart`: re-despacha (borra huérfanos + crea
  fresco) y abre el browser después de que el agente ya esté en el room.
- **Verificá el estado en una pasada**: `saga-ctl status` muestra stack, server (`:port UP/DOWN`),
  worker, daemons y readiness de sockets.
- **Benchmark de latencia**: ver `aidlc-docs/construction/build-and-test/ciclo4-build-and-test.md`.

## Gotchas críticos (leelos antes de tocar)

- **No mates `claude` a lo bruto** (`pkill -f "claude --model"`): esta sesión de desarrollo también
  es un `claude` → te suicidás. Apuntá a `claude_daemon.py` o filtrá por PPID. `saga-ctl stop` ya lo
  hace bien (matchea por basename de script/binario, sin tocar otros `claude`/kitty/tail).
- **Matar daemons con SIGTERM a veces da exit 144** (propaga SIGUSR1 al shell). Si tenés que matar a mano,
  usá SIGKILL o un proceso python aislado; mejor `saga-ctl stop`.
- **El server es BINARIO NATIVO, no Docker.** Se baja con `saga-ctl stop` (mata `livekit-server` por basename),
  NO con `docker`. El NAT de Docker rompía el WebRTC local (dtls timeout) → por eso se sacó.
- **Dispatch EXPLÍCITO, no auto.** El agente entra al room por `create_dispatch` que hace saga-ctl, no por
  auto-dispatch. Si el socket de control falta (Win+Z `FileNotFoundError`), el agente no está en el room →
  `saga-ctl restart` (re-despacha y limpia huérfanos).
- **Plugins de LiveKit se importan a nivel módulo** en `lk/agent.py` (deben registrarse en el main
  thread; importarlos tarde crashea).
- **Orquestación room**: `saga-ctl` pre-arranca server + Claude + orbe ANTES del worker (corre `entry()`
  recién al despacharse). `prewarm_claude()`/`ensure_orb()` son dedup-safe → sin doble-spawn.
- **El stack lo decide la key**, no un flag. No agregar flags para elegir proveedor.
- **`orb.html`: colores de fondo en sRGB** (`THREE.SRGBColorSpace`), sino el bloom revienta a blanco.
- **Whisper `beam>=3`** (greedy/beam=1 dispara loops de alucinación).
- **El orbe sincroniza con la voz real** (Web Audio AnalyserNode sobre el track TTS): el browser es
  participante del room, recibe el track y mide el nivel real.

## Verificación (smoke check)

```bash
.venv/bin/python -m py_compile lk/*.py vc/*.py vcctl.py
.venv/bin/python -m unittest tests.test_pure
```

**CI** (`.github/workflows/tests.yml`): corre `py_compile` de todo el repo + `tests.test_pure` en cada
push/PR a `main`. La suite es stdlib-only (no instala deps). El flujo de voz/Win+Z NO es CI-testeable
(mic/WebRTC/subprocess) → se valida en vivo.
