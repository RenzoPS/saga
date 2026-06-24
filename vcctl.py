#!/usr/bin/env python3
"""saga-ctl: control de los servidores de saga.

  vcctl.py stop     -> cierra los 4 daemons + borra sockets/tmp
  vcctl.py start    -> levanta los 4 daemons (hot, idle esperando 'claude')
  vcctl.py restart  -> stop + start
  vcctl.py status   -> qué está vivo

Diseño a prueba de los problemas que tuvimos con `pkill -f`:
  - Matchea por RUTA EXACTA del script (.py) en el cmdline del proceso, leyendo /proc.
    No usa patrones de shell -> no se auto-matchea, no pega en kitty ni en el `claude` CLI.
  - NUNCA mata el proceso `claude` (el binario que corre el modelo) ni kitty ni el tail:
    sus cmdline no contienen ninguno de los scripts de DAEMONS.
  - Sin PPID, sin árbol de descendientes. Solo los 4 servidores, por pid exacto.
"""
import os
import sys
import time
import signal
import socket
import glob
from pathlib import Path

PROJ = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJ))

# Servidores que se matchean por basename del .py en el cmdline. wake_daemon (Vosk) queda
# en la lista para que `stop` lo baje si alguna vez corre, pero está dormido (fuera de scope).
DAEMONS = ("wake_daemon.py", "claude_daemon.py", "orb_server.py")

# Sockets + temporales a borrar en stop (sin tocar el beep, que se regenera).
TMP_FILES = (
    "/tmp/saga-claude.sock",
    "/tmp/saga-lk-ctl.sock",   # socket de control del agente LiveKit (push-to-talk)
)


def _cmdline(pid: int) -> "list[str]":
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return []
    return [c for c in raw.decode("utf-8", "replace").split("\0") if c]


def _daemon_pids() -> "dict[int, str]":
    """pid -> script, para cada proceso python que corre uno de los DAEMONS.
    Excluye el pid propio. Match por basename exacto en argv: preciso, no pega en
    el `claude` CLI (cmdline 'claude --model...') ni en kitty/tail."""
    me = os.getpid()
    found: "dict[int, str]" = {}
    for entry in glob.glob("/proc/[0-9]*"):
        pid = int(entry.rsplit("/", 1)[1])
        if pid == me:
            continue
        cmd = _cmdline(pid)
        if not cmd:
            continue
        for arg in cmd:
            base = os.path.basename(arg)
            if base in DAEMONS:
                found[pid] = base
                break
    return found


def _alive(pid: int) -> bool:
    return Path(f"/proc/{pid}").exists()


def _lk_agent_pids() -> "dict[int, str]":
    """pid -> 'lk/agent.py' para el worker LiveKit (lk/agent.py start).
    Match preciso: la ruta absoluta del script en el argv (lo lanzamos así). Fallback
    por sufijo 'lk/agent.py' por si alguien lo corre con ruta relativa."""
    from vc.config import LK_AGENT
    target = str(LK_AGENT)
    me = os.getpid()
    found: "dict[int, str]" = {}
    for entry in glob.glob("/proc/[0-9]*"):
        pid = int(entry.rsplit("/", 1)[1])
        if pid == me:
            continue
        cmd = _cmdline(pid)
        for arg in cmd:
            if arg == target or arg.replace("\\", "/").endswith("lk/agent.py"):
                found[pid] = "lk/agent.py"
                break
    return found


def stop() -> int:
    targets = _daemon_pids()
    targets.update(_lk_agent_pids())          # agente/worker LiveKit si corre
    targets.update(_livekit_server_pids())    # binario nativo livekit-server (modo room)
    if not targets:
        print("stop: no hay daemons corriendo")
    else:
        for pid, script in sorted(targets.items()):
            print(f"stop: SIGTERM {pid} ({script})")
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        # esperar salida limpia hasta ~3s
        for _ in range(20):
            if not any(_alive(p) for p in targets):
                break
            time.sleep(0.15)
        # KILL a los que no murieron
        for pid in list(targets):
            if _alive(pid):
                print(f"stop: SIGKILL {pid} (no respondió a TERM)")
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
        time.sleep(0.2)

    # limpiar sockets/tmp
    for f in TMP_FILES:
        try:
            os.unlink(f)
            print(f"stop: borrado {f}")
        except FileNotFoundError:
            pass
        except OSError as e:
            print(f"stop: no pude borrar {f}: {e}")

    left = _daemon_pids()
    left.update(_lk_agent_pids())
    left.update(_livekit_server_pids())
    if left:
        print(f"!! stop: QUEDARON procesos vivos: {left}")
        return 1
    print("stop: OK, 0 procesos vivos, sockets/tmp limpios")
    return 0


def _sock_up(path: str) -> bool:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        s.connect(path)
        return True
    except OSError:
        return False
    finally:
        s.close()


def _port_up(port: int) -> bool:
    s = socket.socket()
    s.settimeout(0.3)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _wait_ready(name: str, probe, timeout: float) -> bool:
    """Espera a que `probe()` dé True hasta `timeout` seg. Imprime el resultado."""
    ok = False
    for _ in range(int(timeout / 0.25)):
        if probe():
            ok = True
            break
        time.sleep(0.25)
    print(f"start: {name} {'HOT' if ok else 'NO levantó a tiempo (revisá el log)'}")
    return ok


def _node_ip() -> str:
    """IP LAN primaria (interfaz de salida por defecto), sin subprocess ni mandar paquetes:
    un socket UDP 'conectado' resuelve la ruta y expone la IP local. LiveKit la anuncia como
    candidato de media (no bindea UDP a loopback) -> tiene que ser la interfaz real."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("1.1.1.1", 80))
        return s.getsockname()[0]
    except OSError:
        # Sin ruta de salida (sin red) -> no hay IP LAN. LiveKit NO bindea media a loopback,
        # así que con node_ip=127.0.0.1 el WebRTC va a fallar con dtls timeout aunque el
        # signaling levante (HOT falso). Avisamos explícito en vez de morir en silencio.
        print("start: ⚠ sin IP LAN (sin ruta de salida) -> node_ip=127.0.0.1; "
              "el audio WebRTC NO va a conectar. Conectá la red y reintentá.")
        return "127.0.0.1"
    finally:
        s.close()


def _livekit_server_pids() -> "dict[int, str]":
    """pid -> 'livekit-server' del binario nativo. Match por basename EXACTO en argv (mismo
    criterio seguro que los daemons; no pega en este `claude`, kitty ni tail)."""
    me = os.getpid()
    found: "dict[int, str]" = {}
    for entry in glob.glob("/proc/[0-9]*"):
        pid = int(entry.rsplit("/", 1)[1])
        if pid == me:
            continue
        for arg in _cmdline(pid):
            if os.path.basename(arg) == "livekit-server":
                found[pid] = "livekit-server"
                break
    return found


def _ensure_agent_dispatched() -> bool:
    """Dispatch EXPLÍCITO del agente al room por API (PROACTIVO): el agente entra al room ANTES
    que el browser, sin depender de qué cliente crea el room ni del timing de arranque. Esto mata
    la race que rompía el auto-dispatch (una pestaña zombie creaba el room sin agente). Idempotente:
    si ya hay un dispatch del agente en el room, no duplica."""
    import asyncio
    import time as _time
    from vc.config import (
        LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, LIVEKIT_ROOM, LIVEKIT_AGENT_NAME,
    )
    from livekit import api
    http_url = LIVEKIT_URL.replace("wss://", "https://").replace("ws://", "http://")

    async def _go() -> str:
        lk = api.LiveKitAPI(http_url, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        try:
            # Borrar dispatches HUÉRFANOS (un worker muerto deja el record en el server; si no se
            # limpia, un create nuevo no re-despacha y el agente nunca entra). Dejamos uno fresco.
            for d in await lk.agent_dispatch.list_dispatch(room_name=LIVEKIT_ROOM):
                try:
                    await lk.agent_dispatch.delete_dispatch(dispatch_id=d.id, room_name=LIVEKIT_ROOM)
                except Exception:  # noqa: BLE001
                    pass
            await lk.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(agent_name=LIVEKIT_AGENT_NAME, room=LIVEKIT_ROOM))
            return "creado"
        finally:
            await lk.aclose()

    def _transient(e: Exception) -> bool:
        # El server abre el puerto de signaling ANTES de tener su registro de nodos listo: el dispatch
        # (Twirp API) puede dar 503 "no response from servers"/unavailable por unos cientos de ms,
        # sobre todo tras un SIGKILL (arranque más lento). Es transitorio -> reintentar.
        s = str(e).lower()
        return "unavailable" in s or "503" in s or "no response from servers" in s

    # Retry con backoff: ~6 intentos en ~5s. El worker ya registró -> apenas el server queda
    # operativo, el create entra. Solo reintentamos el error transitorio; otros fallan rápido.
    last = None
    for i in range(6):
        try:
            res = asyncio.run(_go())
            print(f"start: dispatch del agente '{LIVEKIT_AGENT_NAME}' -> room '{LIVEKIT_ROOM}' ({res})")
            return True
        except Exception as e:  # noqa: BLE001
            last = e
            if _transient(e) and i < 5:
                print(f"start: server aún no listo para el dispatch (intento {i + 1}/6), reintento...")
                _time.sleep(0.8)
                continue
            break
    print(f"start: NO pude despachar el agente por API: {last}")
    return False


def _dispatch_subsystem_ready() -> bool:
    """True si el subsistema AgentDispatch del server YA RESPONDE (un list_dispatch liviano sin 503).
    CLAVE del bug 'primera vez en frío falla, segunda anda': el server abre el puerto de signaling
    (lo damos 'HOT') ANTES de tener listo el agent-dispatch. Si el WORKER registra en esa ventana, el
    server queda sin poder asignarle jobs ('no response from servers') por toda la vida de ese server
    -> Win+Z falla hasta reiniciar. Esperando esto ANTES de lanzar el worker, registra contra un
    server ya listo y no se envenena."""
    import asyncio
    from vc.config import LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, LIVEKIT_ROOM
    from livekit import api
    http_url = LIVEKIT_URL.replace("wss://", "https://").replace("ws://", "http://")

    async def _probe() -> None:
        lk = api.LiveKitAPI(http_url, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        try:
            # timeout DURO: contra un server a medio levantar el list_dispatch puede COLGAR (no dar
            # 503): sin esto saga-ctl se freezea. Con timeout, cada intento corta y _wait_ready reintenta.
            await asyncio.wait_for(
                lk.agent_dispatch.list_dispatch(room_name=LIVEKIT_ROOM), timeout=2.0)
        finally:
            await lk.aclose()

    try:
        asyncio.run(_probe())
        return True
    except Exception:  # noqa: BLE001 - 503/timeout/unavailable mientras el subsistema arranca
        return False


def _has_deepgram() -> bool:
    """¿Hay DEEPGRAM_API_KEY en .env.local? Define el stack real (Deepgram vs fallback)."""
    try:
        from vc.config import ENV_FILE
        from dotenv import load_dotenv
        load_dotenv(ENV_FILE)
        return bool(os.environ.get("DEEPGRAM_API_KEY"))
    except Exception:
        return False


def _start_room() -> int:
    """Modo ROOM (Ciclo 4): levanta el server LiveKit NATIVO + cerebro + orbe + worker, y abre
    el browser cliente. Orden con readiness por pieza. El worker (lk/agent.py start) se registra
    y corre entry() recién cuando el browser entra al room -> por eso pre-arrancamos orbe+claude
    (dedup-safe) para que estén listos antes de abrir el browser y del 1er turno."""
    import subprocess
    from vc.config import (
        CLAUDE_SOCK, ORB_PORT, ORB_URL, LK_AGENT, LK_LOG, LK_CTL_SOCK,
        LIVEKIT_SERVER_BIN, LIVEKIT_CONFIG, LK_SERVER_LOG, LIVEKIT_SIGNAL_PORT,
        LIVEKIT_API_KEY, LIVEKIT_API_SECRET,
    )
    from vc.desktop import ensure_monitor_open
    from vc.claudecli import prewarm_claude
    from vc.orb import ensure_orb

    dg = _has_deepgram()
    print("=" * 60)
    print("start: saga (LiveKit room)")
    print("  server LiveKit local (nativo) + browser cliente publica mic / recibe TTS")
    print("  cerebro -> Claude Code")
    print("  STT/voz -> " + ("Deepgram Nova-3 + Aura-2" if dg else "whisper local + edge-tts [SIN key]"))
    print("=" * 60)

    ensure_monitor_open()   # consola de debug (kitty con tail del log)

    # 1) server nativo (NODE_IP auto-detectado; keys de .env.local)
    if not LIVEKIT_SERVER_BIN.exists():
        print(f"start: NO existe el binario {LIVEKIT_SERVER_BIN}")
        print("start: bajalo (release oficial de livekit/livekit) a ~/.local/bin/livekit-server")
        return 1
    if _livekit_server_pids():
        print(f"start: livekit-server YA corría (pid {sorted(_livekit_server_pids())})")
    else:
        if not (LIVEKIT_API_KEY and LIVEKIT_API_SECRET):
            print("start: faltan LIVEKIT_API_KEY/SECRET en .env.local")
            return 1
        env = dict(os.environ)
        env["NODE_IP"] = _node_ip()
        env["LIVEKIT_KEYS"] = f"{LIVEKIT_API_KEY}: {LIVEKIT_API_SECRET}"
        try:
            logf = open(LK_SERVER_LOG, "ab")
            subprocess.Popen(
                [str(LIVEKIT_SERVER_BIN), "--config", str(LIVEKIT_CONFIG)],
                stdin=subprocess.DEVNULL, stdout=logf, stderr=logf,
                env=env, start_new_session=True,
            )
            print(f"start: livekit-server lanzado  (NODE_IP={env['NODE_IP']}, log: {LK_SERVER_LOG})")
        except OSError as e:
            print(f"start: NO pude lanzar livekit-server: {e}")
            return 1
    _wait_ready("livekit-server", lambda: _port_up(LIVEKIT_SIGNAL_PORT), 15)

    # 2) cerebro caliente + 3) orbe (dedup-safe: si ya están, no-op). open_browser=False:
    # el browser lo abre el paso 5 DESPUÉS del dispatch (si no, se abrían DOS pestañas).
    prewarm_claude()
    ensure_orb(open_browser=False)

    _wait_ready("claude", lambda: _sock_up(str(CLAUDE_SOCK)), 30)
    _wait_ready("orb", lambda: _port_up(ORB_PORT), 10)

    # 3.5) CRÍTICO (fix cold-start): esperar a que el subsistema de agent-dispatch del server RESPONDA
    # ANTES de lanzar el worker. El puerto de signaling abre antes que el agent-dispatch; si el worker
    # registra en esa ventana (cold start, init más lento), el server no puede asignarle jobs y Win+Z
    # falla hasta reiniciar ("primera vez en frío falla, segunda anda"). Con esto, el worker registra
    # contra un server ya listo. (En caliente el probe pasa al toque -> no agrega latencia.)
    _wait_ready("dispatch del server", _dispatch_subsystem_ready, 30)

    # 4) worker en modo room. CRÍTICO: LiveKit hace auto-dispatch SOLO al CREARSE el room.
    # Si el browser entra antes de que el worker REGISTRE, el room se crea sin agente y el
    # worker (que registra tarde) nunca se despacha -> no corre entry() -> no hay socket de
    # control -> Win+Z falla. Por eso esperamos "registered worker" ANTES de abrir el browser.
    running = _lk_agent_pids()
    if running:
        print(f"start: worker YA corría (pid {sorted(running)})")
    else:
        log_pos = LK_LOG.stat().st_size if LK_LOG.exists() else 0
        try:
            logf = open(LK_LOG, "ab")
            subprocess.Popen(
                [sys.executable, str(LK_AGENT), "start"],
                stdin=subprocess.DEVNULL, stdout=logf, stderr=logf,
                start_new_session=True,
            )
            print(f"start: worker (modo room) lanzado  (log: {LK_LOG})")
        except OSError as e:
            print(f"start: NO pude lanzar el worker: {e}")
            return 1

        def _worker_registered() -> bool:
            try:
                with open(LK_LOG, "rb") as f:
                    f.seek(log_pos)
                    return b"registered worker" in f.read()
            except OSError:
                return False
        _wait_ready("worker registrado", _worker_registered, 30)

    worker_ok = bool(_lk_agent_pids())
    print(f"start: worker {'CORRIENDO' if worker_ok else f'NO arrancó -> revisá {LK_LOG}'}")

    # 4.5) DISPATCH explícito del agente al room (proactivo, por API). El agente entra al room y
    # corre entry() -> crea el socket de control ANTES de abrir el browser. Robusto contra pestañas
    # zombie y timing. Probamos que el socket RESPONDE (no solo que el archivo existe): si el worker
    # crasheó dejó un socket stale en disco; con .exists() saltábamos el dispatch -> agente nunca
    # entraba -> Win+Z fallaba. _sock_up() conecta de verdad -> un socket stale cae al dispatch.
    if _sock_up(str(LK_CTL_SOCK)):
        print("start: agente ya en el room (socket de control responde)")
    else:
        _ensure_agent_dispatched()
        _wait_ready("agente en el room", lambda: _sock_up(str(LK_CTL_SOCK)), 15)

    # 5) abrir el browser cliente (el agente YA está en el room -> al entrar, lo encuentra)
    try:
        subprocess.Popen(
            ["xdg-open", ORB_URL], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        print(f"start: abriendo el orbe -> {ORB_URL}")
    except OSError:
        print(f"start: abrí el orbe a mano -> {ORB_URL}")
    print("start: USO -> Win+Z: graba / corta y manda / mata. Silencio ~2s también manda.")
    print("start:        Apagar todo: 'saga-ctl stop'.")
    return 0 if worker_ok else 1


def start() -> int:
    """Único modo: LiveKit room (server nativo + browser cliente). Lo levanta _start_room()."""
    return _start_room()


def status() -> int:
    from vc.config import CLAUDE_SOCK, ORB_PORT, LIVEKIT_SIGNAL_PORT
    print("=== modo === LiveKit / room")
    dg = _has_deepgram()
    print(f"  STT / TTS          {'Deepgram Nova-3 + Aura-2 (key OK)' if dg else 'whisper local + edge-tts (SIN key)'}")
    srv = _livekit_server_pids()
    up = _port_up(LIVEKIT_SIGNAL_PORT)
    print(f"  livekit-server     {('UP ' + str(sorted(srv))) if srv else 'DOWN'}  (:{LIVEKIT_SIGNAL_PORT} {'UP' if up else 'down'})")
    lk = _lk_agent_pids()
    print(f"  agente/worker LK   {'UP ' + str(sorted(lk)) if lk else 'DOWN'}")
    pids = _daemon_pids()
    # wake_daemon (Vosk) está dormido (fuera de scope) -> no aplica al flujo room.
    na = {"wake_daemon.py"}
    print("=== daemons ===")
    for script in DAEMONS:
        live = [p for p, s in pids.items() if s == script]
        if live:
            state = "UP " + str(live)
        elif script in na:
            state = "—   (Vosk dormido, fuera de scope)"
        else:
            state = "DOWN"
        print(f"  {script:18} {state}")
    print("=== readiness ===")
    print(f"  claude.sock   {'UP' if _sock_up(str(CLAUDE_SOCK)) else 'down'}")
    print(f"  orb :{ORB_PORT}     {'UP' if _port_up(ORB_PORT) else 'down'}")
    return 0


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "stop":
        return stop()
    if cmd == "start":
        return start()
    if cmd == "restart":
        rc = stop()
        time.sleep(0.5)
        return start() or rc
    if cmd == "status":
        return status()
    print(f"uso: {sys.argv[0]} [stop|start|restart|status]")
    return 2


if __name__ == "__main__":
    sys.exit(main())
