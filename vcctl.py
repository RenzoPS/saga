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

    # token del orbe (U2): efimero por sesion -> se va con el stop. El proximo start genera uno nuevo.
    from vc.config import reset_orb_token
    reset_orb_token()

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


def _kill_pids(targets: "dict[int, str]") -> None:
    """SIGTERM -> (espera ~3s) -> SIGKILL a los pids dados. Mismo patrón que stop(), reusable para
    relanzar piezas FRESCAS en start (server + worker) sin tocar el resto de los procesos (claude/orb).
    No pega en este `claude`: los targets vienen de los matchers por basename/ruta exacta."""
    if not targets:
        return
    for pid, label in sorted(targets.items()):
        print(f"start: bajando {label} viejo (pid {pid}) para relanzarlo fresco")
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    for _ in range(20):
        if not any(_alive(p) for p in targets):
            break
        time.sleep(0.15)
    for pid in list(targets):
        if _alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    time.sleep(0.2)


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
    from vc.orb import ensure_orb, orb_url_with_token

    # Token del orbe (U2/FR3.1): NO lo reseteamos acá. La rotacion la hace `stop` (y restart = stop+start).
    # Si resetearamos en `start` con el server del orbe ya vivo (start sin stop), el archivo tendria un
    # token nuevo pero el server seguiria validando el viejo en memoria -> URL con token nuevo, server con
    # el viejo = 401. Dejando la rotacion en `stop`, el archivo y el server SIEMPRE quedan sincronizados:
    # tras un stop limpio el archivo no existe y orb_token() genera uno fresco que el server recibe por env.

    dg = _has_deepgram()
    print("=" * 60)
    print("start: saga (LiveKit room)")
    print("  server LiveKit local (nativo) + browser cliente publica mic / recibe TTS")
    print("  cerebro -> Claude Code")
    print("  STT/voz -> " + ("Deepgram Nova-3 + Aura-2" if dg else "whisper local + edge-tts [SIN key]"))
    print("=" * 60)

    ensure_monitor_open()   # consola de debug (kitty con tail del log)

    # 1) server nativo FRESCO. Lo relanzamos en CADA start: los rooms viven en memoria del server ->
    # server fresco = sin rooms zombie de una sesión previa -> el 1er browser crea el room limpio -> el
    # auto-dispatch del worker entra garantizado. (NODE_IP auto-detectado; keys de .env.local.)
    if not LIVEKIT_SERVER_BIN.exists():
        print(f"start: NO existe el binario {LIVEKIT_SERVER_BIN}")
        print("start: bajalo (release oficial de livekit/livekit) a ~/.local/bin/livekit-server")
        return 1
    if not (LIVEKIT_API_KEY and LIVEKIT_API_SECRET):
        print("start: faltan LIVEKIT_API_KEY/SECRET en .env.local")
        return 1
    _kill_pids(_livekit_server_pids())
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

    # 4) worker FRESCO (lk/agent.py start). Lo relanzamos siempre para no arrastrar un worker viejo
    # (saturado / huérfano / apuntando a un server anterior). Con AUTO-DISPATCH nativo NO despachamos
    # por API: el worker registra contra el server y, cuando el browser crea el room, el server lo
    # despacha solo -> entry() -> socket de control. Esperamos "registered worker" para asegurar que
    # ya está listo a recibir el dispatch cuando entre el browser.
    _kill_pids(_lk_agent_pids())
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

    # 5) abrir el browser cliente -> se une al room "saga" -> lo CREA -> el server AUTO-despacha el
    # worker -> entry() corre -> crea el socket de control. El browser es el trigger natural del room
    # (sin cliente no hay sesión, que es lo correcto). Por eso el wait del socket va DESPUÉS de abrirlo.
    # El token viaja UNA vez por la URL de bootstrap (U2): la pagina lo guarda en memoria y lo saca
    # de la barra con replaceState. Sin ?token=, el server responde 401 y el orbe no conecta.
    orb_url = orb_url_with_token()
    try:
        subprocess.Popen(
            ["xdg-open", orb_url], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        print(f"start: abriendo el orbe -> {ORB_URL}")     # sin el token: no lo imprimimos en consola
    except OSError:
        print(f"start: abrí el orbe a mano -> {orb_url}")  # a mano SI lo necesita

    # 6) readiness REAL del agente: esperar a que el socket de control RESPONDA = el agente entró al
    # room (vía el browser) y corrió entry(). Es la confirmación de que Win+Z va a andar.
    sock_ok = _wait_ready("agente en el room (socket de control)",
                          lambda: _sock_up(str(LK_CTL_SOCK)), 30)

    print("start: USO -> Win+Z: graba / corta y manda / mata. Silencio ~2s también manda.")
    print("start:        Apagar todo: 'saga-ctl stop'.")
    return 0 if (worker_ok and sock_ok) else 1


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
