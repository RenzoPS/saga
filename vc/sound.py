"""Beep de notificación compartido (wake daemon + flujo de conversación).
Genera un WAV corto una vez y lo reproduce best-effort con paplay."""

import math
import struct
import wave
import subprocess

from .config import WAKE_BEEP_FILE
from .runtime import log


def ensure_beep() -> None:
    """Genera el beep (dos tonos ascendentes) si no existe. WAV 16-bit mono."""
    if WAKE_BEEP_FILE.exists():
        return
    sr = 44100
    frames = bytearray()

    def tone(freq, dur, vol=0.35):
        n = int(sr * dur)
        for i in range(n):
            env = min(1.0, i / (sr * 0.01), (n - i) / (sr * 0.01))  # fade in/out, sin chasquido
            s = math.sin(2 * math.pi * freq * i / sr) * vol * env
            frames.extend(struct.pack("<h", int(s * 32767)))

    tone(880, 0.07)
    tone(1320, 0.09)
    try:
        with wave.open(str(WAKE_BEEP_FILE), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(bytes(frames))
    except OSError as e:
        log(f"no pude generar beep: {e}")


def play_beep() -> None:
    """Reproduce el beep sin bloquear (best-effort)."""
    try:
        subprocess.Popen(
            ["paplay", str(WAKE_BEEP_FILE)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except OSError as e:
        log(f"no pude reproducir beep: {e}")
