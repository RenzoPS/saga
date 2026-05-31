#!/usr/bin/env python3
"""Prueba rápida de sync TTS↔orbe SIN hacer la vuelta completa (grabar/Claude).

Sintetiza una frase con el MISMO pipeline real (edge-tts → mpg123 → pacat + metering)
y mueve el orbe en estado 'speak'. Sirve para iterar el sync mirando Y escuchando.

Uso:
    .venv/bin/python tools/say.py
    .venv/bin/python tools/say.py "la frase que quieras escuchar"
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vc.orb import ensure_orb, orb_state          # noqa: E402
from vc.tts import TTSStreamer                     # noqa: E402

DEFAULT = ("Hola, esto es una prueba de sincronización. Mirá si la red se mueve "
           "justo cuando hablo, o si va atrasada respecto a mi voz.")


def main() -> int:
    text = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    ensure_orb()
    time.sleep(0.4)            # darle un toque al server/pestaña
    orb_state("speak")
    streamer = TTSStreamer()
    streamer.enqueue(text)
    streamer.finish()
    streamer.wait(timeout=120)
    orb_state("idle")
    return 0


if __name__ == "__main__":
    sys.exit(main())
