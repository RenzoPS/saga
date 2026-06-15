"""Captura de audio del micrófono. Graba hasta recibir señal de stop (SIGUSR1)
o cancelación, emite el nivel del mic al orbe en vivo, y guarda el WAV.

Auto-stop (modo wake): usa el VAD de VOZ de Silero (no energía). Detecta HABLA real,
así ruido/música/ventilador/nivel-de-mic no rompen la detección. El VAD de energía
anterior calibraba un "piso" en los primeros 0.5s asumiendo silencio; si arrancabas a
hablar tras el beep, el piso se inflaba a tu voz y NUNCA latcheaba 'spoke' -> cortaba
siempre a los 6s ('nadie habló') aunque hablaras. Silero no tiene ese problema."""

import os
import signal
import time
import wave
import threading

import numpy as np
import sounddevice as sd

from .config import SAMPLE_RATE, CHANNELS, AUDIO_FILE, PID_FILE, AUTOSTOP_ON_MANUAL
from .runtime import log, _cancel, self_identity
from .orb import orb_state

# Auto-stop por silencio (VAD Silero). Modo wake: siempre (arranca sin Win+Z, hay que
# cortar solo). Flujo Win+Z: según AUTOSTOP_ON_MANUAL (default ON) -> apretás, hablás,
# corta al callar. El 2do Win+Z para cortar a mano sigue funcionando igual.
_AUTOSTOP = os.environ.get("VOICE_WAKE_AUTOSTOP") == "1" or AUTOSTOP_ON_MANUAL
_VAD_HANG_S = 2.0          # silencio (sin HABLA) sostenido tras hablar -> cortar
_VAD_MAX_S = 120.0         # techo de seguridad (2 min): solo frena un runaway
_VAD_START_GRACE_S = 6.0   # margen inicial para empezar a hablar antes de cortar
_VAD_TAIL_S = 12.0         # ventana reciente que analiza Silero por tick (acota costo)
_VAD_EVAL_EVERY_S = 0.35   # cada cuánto correr el VAD (cada llamada ~10-50ms)

# Silero VAD: modelo de VOZ bundleado en faster-whisper (silero_vad_v6.onnx + onnxruntime,
# ya instalados; cero deps nuevas). Se carga en un thread al arrancar la grabación (~450ms)
# para no sumar al import del flujo ni demorar el inicio de la captura.
_vad = {"fn": None, "opts": None, "err": None}


def _load_vad_async() -> None:
    if _vad["fn"] is not None or _vad["err"] is not None:
        return

    def _job():
        try:
            from faster_whisper.vad import get_speech_timestamps, VadOptions, get_vad_model
            get_vad_model()  # calienta el lru_cache del onnx
            _vad["opts"] = VadOptions(
                min_speech_duration_ms=200,   # ignora blips < 0.2s (clicks, golpes)
                min_silence_duration_ms=100,
                speech_pad_ms=30,
            )
            _vad["fn"] = get_speech_timestamps
        except Exception as e:  # noqa: BLE001
            _vad["err"] = e
            log(f"VAD Silero no cargó ({e!r}); auto-stop sólo por techo de duración")

    threading.Thread(target=_job, daemon=True).start()


def _speech_and_silence(audio_i16: np.ndarray):
    """Sobre la cola reciente devuelve (hubo_habla, seg_silencio_al_final) con Silero.
    hubo_habla=True si detectó HABLA en la ventana; silencio = tiempo desde que terminó
    la última habla. (None, 0) si el modelo todavía no cargó -> el caller no corta aún."""
    fn, opts = _vad["fn"], _vad["opts"]
    if fn is None:
        return None, 0.0
    audio_i16 = audio_i16.reshape(-1)   # el buffer del mic viene (N,1); Silero exige 1D
    n_tail = int(_VAD_TAIL_S * SAMPLE_RATE)
    tail = audio_i16[-n_tail:] if len(audio_i16) > n_tail else audio_i16
    audio = tail.astype(np.float32) / 32768.0
    segs = fn(audio, opts)
    tail_s = len(audio) / SAMPLE_RATE
    if not segs:
        return False, tail_s
    return True, tail_s - segs[-1]["end"] / SAMPLE_RATE


def record_until_signaled() -> float:
    PID_FILE.write_text(self_identity())   # pid:starttime (anti PID-recycle)
    stop_event = threading.Event()

    def handler(_sig, _frame):
        stop_event.set()

    signal.signal(signal.SIGUSR1, handler)
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

    orb_state("rec")
    log(f"rec start{' (auto-stop por voz)' if _AUTOSTOP else ''}")

    buf: "list[np.ndarray]" = []

    def callback(indata, _frames, _t, _status):
        buf.append(indata.copy())

    if _AUTOSTOP:
        _load_vad_async()   # arranca la carga del modelo en paralelo a la captura

    spoke = False
    last_eval = 0.0
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
            if elapsed - last_eval < _VAD_EVAL_EVERY_S or not buf:
                continue
            last_eval = elapsed
            had_speech, silence_s = _speech_and_silence(np.concatenate(buf))
            if had_speech is None:
                continue   # modelo aún cargando -> no cortar todavía
            if had_speech:
                spoke = True
            if spoke and silence_s >= _VAD_HANG_S:
                log("auto-stop: silencio tras hablar")
                break
            if not spoke and elapsed >= _VAD_START_GRACE_S:
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
    return duration
