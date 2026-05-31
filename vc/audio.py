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
from .runtime import log, _cancel
from .orb import orb_state, orb_level


def record_until_signaled() -> float:
    PID_FILE.write_text(str(os.getpid()))
    stop_event = threading.Event()

    def handler(_sig, _frame):
        stop_event.set()

    signal.signal(signal.SIGUSR1, handler)
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

    orb_state("rec")
    log("rec start")

    buf: "list[np.ndarray]" = []
    mic_level = [0.0]

    def callback(indata, _frames, _t, _status):
        buf.append(indata.copy())
        a = indata.astype(np.float32) / 32768.0
        mic_level[0] = min(1.0, float(np.sqrt(np.mean(a * a))) * 5.0) if a.size else 0.0

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="int16",
        callback=callback,
    ):
        while not stop_event.is_set() and not _cancel.is_set():
            time.sleep(0.05)
            orb_level(mic_level[0])   # nivel real del mic -> orbe late con tu voz

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
