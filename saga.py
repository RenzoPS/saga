#!/usr/bin/env python3
"""voz -> Claude Code -> voz. Toggle por hotkey. Cancelable.

Entry point fino: la lógica vive en el paquete vc/ (config, runtime, orb,
desktop, audio, stt, session, claudecli, tts, app). El wrapper de Hyprland
sigue llamando a este archivo igual que antes."""

import sys

from vc.app import main

if __name__ == "__main__":
    sys.exit(main())
