#!/usr/bin/env python3
"""vc-ctl: control de los servidores de voice-claude.

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

# Los 4 servidores. Se matchea por basename del .py en el cmdline.
DAEMONS = ("wake_daemon.py", "whisper_daemon.py", "claude_daemon.py", "orb_server.py")

# Sockets + temporales a borrar en stop (sin tocar el beep, que se regenera).
TMP_FILES = (
    "/tmp/voice-claude-whisper.sock",
    "/tmp/voice-claude-claude.sock",
    "/tmp/voice-claude.pid",
    "/tmp/voice-claude.lock",
    "/tmp/voice-claude.abort",
    "/tmp/voice-claude.wav",
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


def stop() -> int:
    targets = _daemon_pids()
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
    if left:
        print(f"!! stop: QUEDARON daemons vivos: {left}")
        return 1
    print("stop: OK, 0 daemons vivos, sockets/tmp limpios")
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


def start() -> int:
    import subprocess
    from vc.config import WHISPER_SOCK, CLAUDE_SOCK, ORB_PORT
    from vc.stt import prewarm_whisper
    from vc.claudecli import prewarm_claude
    from vc.orb import ensure_orb

    running = {s: p for p, s in _daemon_pids().items()}

    # 1) wake_daemon (el listener). Los otros 3 los levantan los prewarm del flujo.
    if "wake_daemon.py" in running:
        print(f"start: wake_daemon ya corría (pid {running['wake_daemon.py']})")
    else:
        subprocess.Popen(
            [sys.executable, str(PROJ / "wake_daemon.py")],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        print("start: wake_daemon lanzado")

    # 2) whisper / claude / orb: idéntico a como los spawnea el flujo (dedup-safe).
    prewarm_whisper()
    prewarm_claude()
    ensure_orb()

    # 3) esperar a que queden HOT (best-effort, con timeout).
    checks = (
        ("whisper", lambda: _sock_up(str(WHISPER_SOCK)), 25),
        ("claude", lambda: _sock_up(str(CLAUDE_SOCK)), 30),
        ("orb", lambda: _port_up(ORB_PORT), 10),
    )
    for name, probe, timeout in checks:
        ok = False
        for _ in range(int(timeout / 0.25)):
            if probe():
                ok = True
                break
            time.sleep(0.25)
        print(f"start: {name} {'HOT' if ok else 'NO levantó a tiempo (revisá el log)'}")

    wake_ok = "wake_daemon.py" in _daemon_pids().values()
    print(f"start: wake {'escuchando' if wake_ok else 'NO corriendo'}")
    return 0 if wake_ok else 1


def status() -> int:
    from vc.config import WHISPER_SOCK, CLAUDE_SOCK, ORB_PORT
    pids = _daemon_pids()
    print("=== daemons ===")
    for script in DAEMONS:
        live = [p for p, s in pids.items() if s == script]
        print(f"  {script:18} {'UP ' + str(live) if live else 'DOWN'}")
    print("=== readiness ===")
    print(f"  whisper.sock  {'UP' if _sock_up(str(WHISPER_SOCK)) else 'down'}")
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
