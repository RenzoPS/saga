# Operación

Cómo prender, apagar, observar y diagnosticar saga. Para el detalle del stack LiveKit/Deepgram, ver `lk/README.md`.

## Ciclo de vida (`saga-ctl`)

```bash
saga-ctl start      # levanta el agente LiveKit + Claude + orbe + monitor
saga-ctl status     # modo, stack (Deepgram vs fallback), daemons, readiness
saga-ctl stop       # apaga todo + limpia sockets/tmp
saga-ctl restart    # stop + start
```

Siempre con el venv del proyecto: `.venv/bin/python`. Correr el agente directo (audio local):
`.venv/bin/python lk/agent.py console`.

## Uso (Win+Z, push-to-talk)

- **idle → Win+Z**: graba.
- **rec → Win+Z** (o ~2s de silencio): corta y manda el turno.
- **busy → Win+Z**: mata la respuesta en curso.
- **Visión**: decí "mirá la pantalla" / "qué ves" → captura con grim, se la manda a Claude, y la borra.

Ver `turn-flow.md` para el detalle.

## Procesos

**Modo LiveKit (default):** `lk/agent.py console` (agente) · `claude_daemon.py` (cerebro) ·
`orb/orb_server.py` (orbe). El Win+Z (`saga.py`) es efímero.

**Modo clásico (`VOICE_LIVEKIT=0`):** `whisper_daemon.py` · `claude_daemon.py` · `orb_server.py` ·
(opcional) `wake_daemon.py`.

Ver procesos:
```bash
pgrep -af "lk/agent.py|claude_daemon|orb_server"
```

## Logs y monitor

- **`saga.log`** — log principal (rotativo a 512KB → `.log.old`, perms 0o600 porque tiene transcripciones).
- **`livekit_agent.log`** — log del agente LiveKit.
- **Monitor** — `saga-ctl start` abre una ventana kitty (workspace 10) con `tail -F saga.log`.

```bash
tail -F saga.log
```

## Variables de entorno

| Var | Default | Qué hace |
|-----|---------|----------|
| `VOICE_LIVEKIT` | `1` | `=0` vuelve al flujo clásico (whisper/edge) |
| `VOICE_CLAUDE_SAFE` | (off) | `=1` desactiva `--dangerously-skip-permissions` |
| `VOICE_CLAUDE_MEM` | `0` | `=1` activa claude-mem en voz (+2-7s/turno; respawnear daemon) |
| `VOICE_WAKE_ENABLED` | `0` | `=1` activa el wake word Vosk (requiere el modelo en `models/`) |
| `VOICE_AUTOSTOP` | `1` | auto-stop por silencio en Win+Z clásico |
| `ORB_PORT` | `8777` | puerto del server del orbe |

El stack STT/TTS **no es env**: lo decide la presencia de `DEEPGRAM_API_KEY` en `.env.local`.

## Diagnóstico

```bash
.venv/bin/python saga.py --doctor    # binarios, deps, daemons, config
```

Binarios requeridos: `claude` (crítico), `mpg123`/`pacat`/`paplay` (audio), `grim` (screenshot),
`hyprctl`/`kitty`/`xdg-open` (escritorio).

## Gotchas críticos (leelos antes de tocar)

- **No mates `claude` a lo bruto** (`pkill -f "claude --model"`): esta sesión de desarrollo también
  es un `claude` → te suicidás. Apuntá a `claude_daemon.py` o filtrá por PPID.
- **Plugins de LiveKit se importan a nivel módulo** en `lk/agent.py` (deben registrarse en el main
  thread; importarlos tarde crashea).
- **Single-owner**: el agente levanta orbe + prewarm Claude. `vcctl` no los duplica.
- **El stack lo decide la key**, no un flag. No agregar flags para elegir proveedor.
- **`orb.html`: colores de fondo en sRGB** (`THREE.SRGBColorSpace`), sino el bloom revienta a blanco.
- **Whisper `beam>=3`** (greedy/beam=1 dispara loops de alucinación).
- **El orbe NO sincroniza con el audio real** — anima stylized, a propósito (sync HTTP audio/visual nunca quedó fino).

## Verificación (smoke check)

```bash
.venv/bin/python -m py_compile lk/*.py vc/*.py vcctl.py
.venv/bin/python -m unittest tests.test_pure
```
