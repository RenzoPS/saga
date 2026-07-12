# U6 — saga-ctl orquestación (modo room) · Code Generation Plan (Ciclo 4)

> Hacer saga arrancable/parable con un comando en modo room. Hoy corre porque levanté 3 procesos a mano.
> Depende de U1 (server nativo), U2 (worker start), U3 (cliente). `saga-ctl` = wrapper fino → `vcctl.py`.

## Qué cambia
`vcctl.py` hoy: `_start_livekit()` lanza `lk/agent.py console`. Agrego un path **room** que orquesta las 5
piezas + abre el browser, y que `stop` baje también el binario nativo.

## Stages condicionales (Per-Unit Loop)
- Functional/NFR/Infra Design — SKIP (script de orquestación; sin modelos/lógica nueva; infra ya decidida en U1).
- Code Generation — EXECUTE.

## Decisiones técnicas
1. **Selección de transporte**: `SAGA_TRANSPORT` (default `room`; `console` = fallback dev). Dentro de
   `_start_livekit()`: si room → `_start_room()`, si console → el path actual (`lk/agent.py console`).
2. **NODE_IP auto-detect** (sin subprocess): truco socket UDP — `s.connect(("1.1.1.1",80)); s.getsockname()[0]`
   → IP LAN primaria. Se exporta como env `NODE_IP` al lanzar el server.
3. **Orden de arranque room** (con readiness por pieza):
   1. server nativo `~/.local/bin/livekit-server --config livekit.yaml` con env `NODE_IP` + `LIVEKIT_KEYS`
      (armada de `LIVEKIT_API_KEY/SECRET` de .env.local). Readiness: puerto 7880.
   2. `prewarm_claude()` (cerebro caliente antes del 1er turno). Readiness: claude.sock.
   3. `ensure_orb()` (orb_server: sirve la página + /token). Readiness: puerto 8777. (dedup-safe.)
   4. worker `lk/agent.py start` (se registra, espera dispatch). Readiness: proc vivo (el "registered" lo
      confirma el log; no hay socket que probar).
   5. abrir el browser → `xdg-open http://127.0.0.1:8777/` (respeta el browser default; no falla si no anda).
      Al unirse → el server despacha → el worker corre entry() (orb+claude ya están → dedup, sin doble-spawn).
4. **stop**: además de los daemons .py + worker, matar el binario `livekit-server` (match por basename
   `livekit-server` en el cmdline, NO por patrón shell). Limpiar también el socket de control.

## Archivos afectados
| Archivo | Acción | Detalle |
|---|---|---|
| `vc/config.py` | MOD | `LIVEKIT_SERVER_BIN`, `LIVEKIT_CONFIG`, `LK_SERVER_LOG`, `SAGA_TRANSPORT`, helper `livekit_keys()` |
| `vcctl.py` | MOD | `_start_room()`, `_livekit_server_pids()` (para stop), NODE_IP detect, route por SAGA_TRANSPORT, status room |

## Riesgos / mitigación
- **El worker prewarmea claude + orbe on-dispatch**: por eso vcctl los pre-arranca (dedup-safe) → orb_server
  está ANTES de abrir el browser, y claude caliente antes del 1er turno.
- **Matar el binario nativo sin tocar otros procesos**: match por basename exacto `livekit-server` en argv
  (mismo patrón seguro que los daemons; no pega en este claude ni en kitty).
- **NODE_IP cambia con la red**: se re-detecta en cada `start` (no se hardcodea). Si no hay red, cae a la IP
  que devuelva el truco (o se loguea el fallo).
- **No romper console/clásico**: el path room es aditivo; `SAGA_TRANSPORT=console` y `VOICE_LIVEKIT=0` siguen.

---

# PART 1 — PLANNING (este documento)
- [x] Step 1-5: contexto (leído vcctl.py + wrapper + helpers), plan, archivos, resumen
- [x] Step 6-9: log aprobación + "Aprobar y generar" + registrado + Part 1 OK

# PART 2 — GENERATION
- [x] **Step 10**: `vc/config.py` — constantes room (LIVEKIT_SERVER_BIN/CONFIG, LK_SERVER_LOG, SIGNAL_PORT, SAGA_TRANSPORT)
- [x] **Step 11**: `vcctl.py` — `_node_ip()` (socket trick) + `_livekit_server_pids()` + `_wait_ready()`
- [x] **Step 12**: `vcctl.py` — `_start_room()` (server→claude→orb→worker→browser, readiness por pieza)
- [x] **Step 13**: `vcctl.py` — routing por `SAGA_TRANSPORT` en `start()` + `stop()` mata el binario + `status()` room
- [~] **Step 14**: Verificación
  - [x] `py_compile vcctl.py vc/config.py` OK
  - [x] `saga-ctl status` muestra room correcto (server UP :7880, worker, claude, orb)
  - [x] `saga-ctl stop` bajó server nativo + worker + claude + orb (SIGTERM→SIGKILL), 0 vivos, sin tocar este claude
  - [ ] `saga-ctl start` (abre monitor + browser → lo corre el USUARIO) + turno de voz en vivo
- [x] **Step 15**: Summary + aidlc-state.md

## Criterio de "U6 hecho"
- `saga-ctl start` levanta server nativo (NODE_IP auto) + claude + orb + worker, abre el browser, readiness OK.
- `saga-ctl stop` baja todo (incluido el binario), limpia sockets, sin matar este claude.
- `saga-ctl status` refleja el modo room.
- console/clásico intactos (fallback).
