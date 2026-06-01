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

# Auto-stop por silencio (solo modo wake: arranca sin Win+Z, hay que cortar solo).
# Se activa con env VOICE_WAKE_AUTOSTOP=1; el flujo Win+Z normal NO lo usa.
_AUTOSTOP = os.environ.get("VOICE_WAKE_AUTOSTOP") == "1"
_VAD_HANG_S = 1.5        # silencio sostenido tras hablar -> cortar (margen p/ pausas naturales)
_VAD_MAX_S = 30.0        # techo duro (no grabar para siempre si nunca calla)
_VAD_START_GRACE_S = 6.0  # margen inicial para empezar a hablar antes de cortar por silencio
_VAD_LEADIN_S = 0.5      # ignorar el arranque para 'spoke' (tapa el beep + warmup del stream); ahí se mide el piso de ruido
_VAD_DEBOUNCE_S = 0.25   # la energía debe SOSTENERSE esto para contar como voz (un blip/click/beep no cuenta)
_VAD_MIN_FLOOR = 500.0   # piso absoluto del umbral (RMS int16): ruido ambiente bajo no dispara


def record_until_signaled() -> float:
    PID_FILE.write_text(self_identity())   # pid:starttime (anti PID-recycle)
    stop_event = threading.Event()

    def handler(_sig, _frame):
        stop_event.set()

    signal.signal(signal.SIGUSR1, handler)
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

    orb_state("rec")
    log(f"rec start{' (auto-stop por silencio)' if _AUTOSTOP else ''}")

    buf: "list[np.ndarray]" = []

    # Estado VAD (solo modo wake). Se actualiza en el callback de audio.
    #  - lead-in: los primeros _VAD_LEADIN_S no cuentan para 'spoke'; ahí se promedia
    #    el ruido ambiente (y se ignora el beep del turno, que entra por el parlante).
    #  - debounce: la energía debe sostenerse _VAD_DEBOUNCE_S para declarar voz -> un
    #    transitorio (click, beep, golpe) no latchea 'spoke' y no dispara grabaciones vacías.
    vad = {"frames": 0, "amb_sum": 0.0, "amb_n": 0, "floor": None, "thresh": _VAD_MIN_FLOOR,
           "spoke": False, "speech_since": None, "silence_since": None}

    def callback(indata, _frames, _t, _status):
        buf.append(indata.copy())
        if not _AUTOSTOP:
            return
        rms = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2)) + 1e-9)
        vad["frames"] += len(indata)
        if vad["frames"] / SAMPLE_RATE < _VAD_LEADIN_S:   # lead-in: medir ambiente, no detectar voz
            vad["amb_sum"] += rms
            vad["amb_n"] += 1
            return
        if vad["floor"] is None:                          # finalizar piso = promedio del ambiente
            vad["floor"] = vad["amb_sum"] / max(vad["amb_n"], 1)
            vad["thresh"] = max(vad["floor"] * 3.0, _VAD_MIN_FLOOR)
        now = time.monotonic()
        if rms > vad["thresh"]:
            if vad["speech_since"] is None:
                vad["speech_since"] = now
            if not vad["spoke"] and now - vad["speech_since"] >= _VAD_DEBOUNCE_S:
                vad["spoke"] = True   # energía sostenida -> recién acá es voz de verdad
            if vad["spoke"]:
                vad["silence_since"] = None
        else:
            vad["speech_since"] = None   # se cortó: hay que volver a sostener para latchear
            if vad["spoke"] and vad["silence_since"] is None:
                vad["silence_since"] = now

    t0 = time.monotonic()
    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="int16",
        callback=callback,
    ):
        while not stop_event.is_set() and not _cancel.is_set():
            time.sleep(0.05)   # el orbe anima stylized en 'rec' (no recibe nivel real)
            if not _AUTOSTOP:
                continue
            elapsed = time.monotonic() - t0
            if elapsed >= _VAD_MAX_S:
                log("auto-stop: techo de duración")
                break
            sil = vad["silence_since"]
            if vad["spoke"] and sil is not None and time.monotonic() - sil >= _VAD_HANG_S:
                log("auto-stop: silencio tras hablar")
                break
            if not vad["spoke"] and elapsed >= _VAD_START_GRACE_S:
                log("auto-stop: nadie habló")
                break

    log(f"rec stop. chunks={len(buf)}")
    if not buf:
        return 0.0

    audio = np.concatenate(buf)
    with wave.open(str(AUDIO_FILE), "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(audio.tobytes())
    os.chmod(AUDIO_FILE, 0o600)   # tu voz -> solo el dueño puede leer el wav
    duration = len(audio) / SAMPLE_RATE
    log(f"wav saved {AUDIO_FILE} duration={duration:.2f}s")
    # Si el VAD nunca detectó voz sostenida (modo wake), el audio es silencio/ruido.
    # Devolver 0 -> el flujo lo trata como turno corto y NO transcribe: así Whisper no
    # alucina (listas de números, "suscríbete", etc.) sobre ambiente y no lo manda a Claude.
    if _AUTOSTOP and not vad["spoke"]:
        log("descartado: no se detectó voz -> sin transcribir (anti-alucinación)")
        return 0.0
    return duration
