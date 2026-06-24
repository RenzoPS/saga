#!/usr/bin/env python3
"""saga: entry point fino del hotkey. Win+Z (Hyprland) -> vc.app:main -> manda 'press'
al agente LiveKit por el socket de control. `saga --doctor` corre el health check.

La voz (STT/LLM/TTS/turnos) vive en el agente (lk/agent.py); el paquete vc/ tiene los
helpers reusados (config, runtime, session, claudecli, orb, desktop, doctor, app)."""

import sys

from vc.app import main

if __name__ == "__main__":
    sys.exit(main())
