"""Integración con el escritorio (Hyprland): notificaciones, ventana monitor
con el log, y captura de pantalla con grim."""

import os
import subprocess
from pathlib import Path

from .config import (
    SCREENSHOT_PATH,
    MONITOR_CLASS,
    MONITOR_WORKSPACE,
    LOG_FILE,
)
from .runtime import log


def take_screenshot() -> "Path | None":
    """Captura pantalla con grim. Devuelve path o None si fallo."""
    try:
        result = subprocess.run(
            ["grim", str(SCREENSHOT_PATH)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            log(f"grim FAIL rc={result.returncode} stderr={result.stderr[:200]}")
            return None
        if not SCREENSHOT_PATH.exists() or SCREENSHOT_PATH.stat().st_size == 0:
            return None
        os.chmod(SCREENSHOT_PATH, 0o600)   # captura de pantalla = puede tener secretos -> solo el dueño
        size_kb = SCREENSHOT_PATH.stat().st_size // 1024
        log(f"screenshot saved {size_kb}KB")
        return SCREENSHOT_PATH
    except Exception as e:
        log(f"grim EXC: {type(e).__name__}: {e}")
        return None


def ensure_monitor_open() -> None:
    """Abre kitty con tail del log en workspace MONITOR_WORKSPACE si no esta abierta."""
    try:
        clients = subprocess.check_output(
            ["hyprctl", "clients"], text=True, timeout=2
        )
        if MONITOR_CLASS in clients:
            return
    except Exception as e:
        log(f"hyprctl clients fail: {type(e).__name__}: {e}")
    cmd = (
        f"[workspace {MONITOR_WORKSPACE}] "
        f"kitty --class {MONITOR_CLASS} --title 'saga monitor' "
        f"-e tail -n 80 -F {LOG_FILE}"
    )
    subprocess.Popen(
        ["hyprctl", "dispatch", "exec", cmd],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    log(f"monitor kitty spawned on ws{MONITOR_WORKSPACE}")
