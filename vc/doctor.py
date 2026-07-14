"""Health check: `saga.py --doctor`. Read-only, no toca el flujo de voz.
Verifica binarios, deps, daemons, config -> dice qué falla en vez de adivinar."""

import shutil
import socket
import importlib
import urllib.request

from .config import (
    CLAUDE_SOCK, ORB_URL, CLAUDE_MEM_DIR, CLAUDE_MODEL,
    WHISPER_SIZE, WHISPER_BEAM, CLAUDE_PERMISSION_MODE, SESSION_FILE,
    SAGA_SETTINGS, _SAGA_SETTINGS,
)

OK, BAD, INFO = "\033[32m✓\033[0m", "\033[31m✗\033[0m", "\033[33m○\033[0m"


def _sock_up(path) -> bool:
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.3)
        s.connect(str(path))
        s.close()
        return True
    except OSError:
        return False


def _http_up(url: str) -> bool:
    try:
        urllib.request.urlopen(url, timeout=0.5)
        return True
    except Exception:
        return False


def doctor() -> int:
    fails = 0

    def line(mark, label, detail=""):
        print(f"  {mark} {label}{('  — ' + detail) if detail else ''}")

    print("\nsaga doctor\n")

    # --- binarios del sistema (críticos: claude; resto importante) ---
    print("Binarios:")
    crit = {"claude": True, "mpg123": True, "pacat": True, "grim": False, "hyprctl": False}
    for b, critical in crit.items():
        path = shutil.which(b)
        if path:
            line(OK, b, path)
        else:
            line(BAD if critical else INFO, b, "NO encontrado en PATH")
            if critical:
                fails += 1

    # --- deps Python (críticas) ---
    print("\nDependencias Python:")
    for m in ("faster_whisper", "sounddevice", "edge_tts", "numpy"):
        try:
            importlib.import_module(m)
            line(OK, m)
        except Exception as e:
            line(BAD, m, f"{type(e).__name__}")
            fails += 1

    # --- daemons (no estar corriendo NO es error: arrancan en el Win+Z) ---
    print("\nDaemons (○ = apagado, arranca solo en Win+Z):")
    line(OK if _sock_up(CLAUDE_SOCK) else INFO, "claude daemon", str(CLAUDE_SOCK))
    line(OK if _http_up(ORB_URL + "healthz") else INFO, "orb server", ORB_URL)

    # --- config ---
    print("\nConfig:")
    line(OK, "modelo Claude", CLAUDE_MODEL)
    line(OK, "Whisper", f"{WHISPER_SIZE} (beam {WHISPER_BEAM})")
    line(OK if CLAUDE_MEM_DIR else INFO, "claude-mem", CLAUDE_MEM_DIR or "no detectado (sin memoria)")
    line(OK, "permisos", f"--permission-mode {CLAUDE_PERMISSION_MODE} (sin god-mode)")
    # El guard es la capa DURA (catastrófico + malas prácticas de git). Si el settings no se pudo
    # escribir, el hook NO está cableado -> esa capa no existe. Hay que gritarlo, no callarlo:
    # el usuario tiene que saber que está menos protegido de lo que cree.
    line(OK if _SAGA_SETTINGS else BAD, "guard (hook)",
         f"activo ({SAGA_SETTINGS})" if _SAGA_SETTINGS
         else "NO CABLEADO — falló el settings: sin red anti-catastrófico")
    line(OK if SESSION_FILE.exists() else INFO, "session.json",
         "existe" if SESSION_FILE.exists() else "no existe (sesión nueva en el próximo turno)")

    print(f"\n{'TODO OK' if fails == 0 else f'{fails} problema(s) crítico(s)'}\n")
    return 0 if fails == 0 else 1
