#!/usr/bin/env python3
"""Win+Z (hotkey de Hyprland) -> manda 'press' al agente LiveKit por el socket de control.

Entry point fino (`saga = vc.app:main`). El agente (lk/agent.py) es dueño del audio/streaming/
turnos; acá sólo le avisamos del toque del hotkey. `saga --doctor` corre el health check."""

import sys

from .runtime import log


def _livekit_press() -> int:
    """Win+Z: manda 'press' al agente por el socket de control (push-to-talk: 1er toque escucha,
    2do manda el turno, 3ro corta). Si el agente no responde, avisa."""
    import socket
    from .config import LK_CTL_SOCK

    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(2.0)
        s.connect(str(LK_CTL_SOCK))
        s.sendall(b"press\n")
        s.recv(64)
        s.close()
        log("Win+Z -> press")
        return 0
    except OSError as e:
        log(f"Win+Z: agente no responde ({type(e).__name__}); ¿corriste 'saga-ctl start'?")
        return 1


def main() -> int:
    if "--doctor" in sys.argv:
        from .doctor import doctor
        return doctor()
    return _livekit_press()


if __name__ == "__main__":
    sys.exit(main())
