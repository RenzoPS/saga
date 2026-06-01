"""Captura de audio del micrófono. Graba hasta recibir señal de stop (SIGUSR1)
o cancelación, emite el nivel del mic al orbe en vivo, y guarda el WAV."""

import os
import signal
import time
import wave
import threading

import numpy as np
import sounddevice as sd

from .config import SAMPLE_RATE, CHANNELS, AUDIO_FILE, PID_FILE
from .runtime import log, _cancel, self_identity
from .orb import orb_state


def record_until_signaled() -> float:
    PID_FILE.write_text(self_identity())   # pid:starttime (anti PID-recycle)
    stop_event = threading.Event()

    def handler(_sig, _frame):
        stop_event.set()

    signal.signal(signal.SIGUSR1, handler)
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

    orb_state("rec")
    log("rec start")

    buf: "list[np.ndarray]" = []

    def callback(indata, _frames, _t, _status):
        buf.append(indata.copy())

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="int16",
        callback=callback,
    ):
        while not stop_event.is_set() and not _cancel.is_set():
            time.sleep(0.05)   # el orbe anima stylized en 'rec' (no recibe nivel real)

    log(f"rec stop. chunks={len(buf)}")
    if not buf:
        return 0.0

    audio = np.concatenate(buf)
    with wave.open(str(AUDIO_FILE), "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(audio.tobytes())
    duration = len(audio) / SAMPLE_RATE
    log(f"wav saved {AUDIO_FILE} duration={duration:.2f}s")
    return duration
