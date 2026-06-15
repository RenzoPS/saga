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
    "/tmp/voice-claude-lk-ctl.sock",   # socket de control del agente LiveKit (push-to-talk)
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
    """pid -> 'lk/agent.py' para el agente LiveKit (lk/agent.py console).
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
    targets.update(_lk_agent_pids())   # incluye el agente LiveKit si está corriendo
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


def _has_deepgram() -> bool:
    """¿Hay DEEPGRAM_API_KEY en .env.local? Define el stack real (Deepgram vs fallback)."""
    try:
        from vc.config import ENV_FILE
        from dotenv import load_dotenv
        load_dotenv(ENV_FILE)
        return bool(os.environ.get("DEEPGRAM_API_KEY"))
    except Exception:
        return False


def _start_livekit() -> int:
    """Modo LiveKit: el agente (lk/agent.py console) es dueño del audio/streaming/
    chunks/VAD/turn detection/barge-in Y de levantar el orbe + precalentar Claude
    (single-owner: lo hace SOLO el agente, no acá -> sin doble-spawn). vcctl sólo
    lanza el agente, abre el monitor, y espera readiness."""
    import subprocess
    from vc.config import CLAUDE_SOCK, ORB_PORT, LK_AGENT, LK_LOG
    from vc.desktop import ensure_monitor_open

    dg = _has_deepgram()
    print("=" * 60)
    print("start: MODO LIVEKIT ACTIVO  (VOICE_LIVEKIT=1)")
    print("  audio / streaming / chunks / VAD / barge-in -> LiveKit")
    print("  cerebro -> Claude Code")
    if dg:
        print("  STT -> Deepgram Nova-3 (streaming)   |   voz -> Deepgram Aura-2 (es)")
    else:
        print("  STT -> faster-whisper local (lento)  |   voz -> edge-tts   [SIN key Deepgram]")
    print("  Win+Z: graba / corta y manda / mata. Silencio ~2s también manda.")
    print("=" * 60)

    ensure_monitor_open()   # consola de debug (kitty con tail del log). El agente levanta orbe+claude.

    running = _lk_agent_pids()
    if running:
        print(f"start: agente LiveKit YA corría (pid {sorted(running)})")
    else:
        try:
            logf = open(LK_LOG, "ab")   # el hijo hereda el fd; el padre sale enseguida
            subprocess.Popen(
                [sys.executable, str(LK_AGENT), "console"],
                stdin=subprocess.DEVNULL, stdout=logf, stderr=logf,
                start_new_session=True,
            )
            print(f"start: agente LiveKit lanzado  (log: {LK_LOG})")
        except OSError as e:
            print(f"start: NO pude lanzar el agente LiveKit: {e}")
            return 1

    # readiness: cerebro + orbe (el whisper vive dentro del agente, no hay socket que probar)
    for name, probe, timeout in (
        ("claude", lambda: _sock_up(str(CLAUDE_SOCK)), 30),
        ("orb", lambda: _port_up(ORB_PORT), 10),
    ):
        ok = False
        for _ in range(int(timeout / 0.25)):
            if probe():
                ok = True
                break
            time.sleep(0.25)
        print(f"start: {name} {'HOT' if ok else 'NO levantó a tiempo (revisá el log)'}")

    time.sleep(1.0)   # darle al agente un momento para crashear si va a crashear
    lk_ok = bool(_lk_agent_pids())
    print(f"start: agente LiveKit {'CORRIENDO' if lk_ok else f'NO arrancó -> revisá {LK_LOG}'}")
    print("start: USO -> Win+Z: 1) graba  2) corta y manda  3) mata. Silencio ~2s también manda.")
    print("start:        Apagar todo: 'vc-ctl stop'. Modo clásico: VOICE_LIVEKIT=0.")
    return 0 if lk_ok else 1


def start() -> int:
    import subprocess
    from vc.config import WHISPER_SOCK, CLAUDE_SOCK, ORB_PORT, WAKE_ENABLED, LIVEKIT_ENABLED
    from vc.stt import prewarm_whisper
    from vc.claudecli import prewarm_claude
    from vc.orb import ensure_orb

    if LIVEKIT_ENABLED:
        return _start_livekit()

    running = {s: p for p, s in _daemon_pids().items()}

    # 1) wake_daemon (el listener). Default DESACTIVADO -> el trigger es Win+Z.
    # El código del daemon queda intacto; VOICE_WAKE_ENABLED=1 lo vuelve a lanzar.
    if not WAKE_ENABLED:
        print("start: wake DESACTIVADO (trigger = Win+Z; VOICE_WAKE_ENABLED=1 para reactivar)")
    elif "wake_daemon.py" in running:
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

    if not WAKE_ENABLED:
        print("start: listo (wake desactivado, Win+Z andando)")
        return 0
    wake_ok = "wake_daemon.py" in _daemon_pids().values()
    print(f"start: wake {'escuchando' if wake_ok else 'NO corriendo'}")
    return 0 if wake_ok else 1


def status() -> int:
    from vc.config import WHISPER_SOCK, CLAUDE_SOCK, ORB_PORT, LIVEKIT_ENABLED
    print(f"=== modo === {'LIVEKIT (VOICE_LIVEKIT=1)' if LIVEKIT_ENABLED else 'clásico (Win+Z)'}")
    dg = _has_deepgram()
    print(f"  STT / TTS          {'Deepgram Nova-3 + Aura-2 (key OK)' if dg else 'whisper local + edge-tts (SIN key)'}")
    lk = _lk_agent_pids()
    print(f"  agente LiveKit     {'UP ' + str(sorted(lk)) if lk else 'DOWN'}")
    pids = _daemon_pids()
    # En modo LiveKit, whisper_daemon y wake_daemon NO se usan (el Whisper vive dentro
    # del agente; no hay wake). Se marcan "n/a" para no confundir con un fallo.
    # whisper_daemon: en LiveKit con Deepgram NO se usa (STT en la nube); whisper sólo
    # es fallback dentro del agente si falta la key. wake_daemon: no aplica.
    na = {"whisper_daemon.py", "wake_daemon.py"} if LIVEKIT_ENABLED else set()
    print("=== daemons ===")
    for script in DAEMONS:
        live = [p for p, s in pids.items() if s == script]
        if live:
            state = "UP " + str(live)
        elif script in na:
            state = "—   (no aplica en modo LiveKit)"
        else:
            state = "DOWN"
        print(f"  {script:18} {state}")
    print("=== readiness ===")
    if _sock_up(str(WHISPER_SOCK)):
        wsock = "UP"
    elif LIVEKIT_ENABLED:
        wsock = "n/a (STT=Deepgram)" if dg else "n/a (whisper en el agente)"
    else:
        wsock = "down"
    print(f"  whisper.sock  {wsock}")
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
