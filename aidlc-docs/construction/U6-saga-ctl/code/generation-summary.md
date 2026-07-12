# U6 — saga-ctl orquestación (modo room) · Generation Summary (Ciclo 4)

> `saga-ctl start/stop/status` para modo room. Hoy saga corría porque se levantaban 3 procesos a mano;
> U6 lo hace arrancable/parable con un comando + auto-detecta NODE_IP.

## Archivos modificados
- **`vc/config.py`** — constantes room: `LIVEKIT_SERVER_BIN` (~/.local/bin/livekit-server), `LIVEKIT_CONFIG`
  (livekit.yaml), `LK_SERVER_LOG`, `LIVEKIT_SIGNAL_PORT` (7880), `SAGA_TRANSPORT` (default `room`, `console` = fallback).
- **`vcctl.py`**:
  - `_node_ip()` — IP LAN primaria por truco socket UDP (sin subprocess); se exporta como env `NODE_IP`.
  - `_livekit_server_pids()` — match del binario `livekit-server` por basename exacto en argv (seguro: no pega
    en este claude/kitty/tail), para que `stop` lo baje.
  - `_wait_ready()` — helper de readiness con timeout.
  - `_start_room()` — orden con readiness: server nativo (NODE_IP + LIVEKIT_KEYS de .env.local) → `prewarm_claude()`
    → `ensure_orb()` → worker `lk/agent.py start` → `xdg-open` del orbe. orbe+claude pre-arrancados (dedup-safe)
    para estar listos antes del browser y del 1er turno (el worker corre entry() recién al despacharse).
  - `start()` — rutea: `SAGA_TRANSPORT=room` → `_start_room()`; si no, el path console actual.
  - `stop()` — agrega el binario nativo a los targets (SIGTERM→SIGKILL); check final incluye worker + server.
  - `status()` — muestra `LIVEKIT/room`, estado del `livekit-server` (proc + puerto), worker, daemons.

## Verificación
| Check | Resultado |
|---|---|
| `py_compile vcctl.py vc/config.py` | ✅ |
| `saga-ctl status` (room) | ✅ server UP :7880, worker UP, claude UP, orb UP |
| `saga-ctl stop` | ✅ bajó server nativo + worker + claude + orb (SIGTERM→SIGKILL), 0 vivos, sockets limpios, **sin tocar este claude** |
| `saga-ctl start` + voz en vivo | ⏳ lo corre el USUARIO (abre monitor kitty + browser en su sesión Hyprland) |

## Lo que NO cambia
- El path console (`SAGA_TRANSPORT=console`) y el clásico (`VOICE_LIVEKIT=0`) quedan intactos (fallback).
- El binario `livekit-server` vive en `~/.local/bin` (fuera del repo).

## Pendiente
- Confirmación en vivo de `saga-ctl start` (bring-up completo + turno de voz) por el usuario.
- README/CLAUDE.md: actualizar el modo default a room (al cerrar el ciclo, con U4/U5).
