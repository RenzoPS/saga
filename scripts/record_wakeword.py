#!/usr/bin/env python3
"""Graba muestras reales de "hey saga" (tu voz) para fine-tune del wake word.

Por qué: el modelo sintético (piper + ACAV) no flashea, pero tu voz rioplatense le
cae en scores bajos (cuesta detectarte). Agregar TUS grabaciones al training sube
tu recall drásticamente. Las mismas muestras sirven para speaker verification (Ciclo 3).

Channel matching: grabá con el MISMO mic que vas a usar (el de la laptop), a la
distancia real de uso. El modelo aprende tu voz a través de ese mic.

Uso:
    .venv/bin/python scripts/record_wakeword.py            # 50 muestras (default)
    .venv/bin/python scripts/record_wakeword.py 80         # 80 muestras

Salida: recordings/hey_saga/user_000.wav ...  (16kHz mono 16-bit, formato del pipeline)
Resume: si el dir ya tiene grabaciones, continúa desde donde quedó.
Integrar al training: scripts/finetune_wakeword.py (siguiente paso).
"""

import audioop
import os
import sys
import time
import wave

import pyaudio

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT_DIR = os.path.join(_ROOT, "recordings", "hey_saga")

# Formato destino = el que consume el pipeline de livekit-wakeword.
_TARGET_SR = 16000
_REC_SECONDS = 1.6          # ventana por muestra (suficiente para "hey saga")
_CHANNELS = 1
_FMT = pyaudio.paInt16

# Consejos de variación: el modelo generaliza mejor si variás condiciones.
_TIPS = [
    "decílo normal, como hablás siempre",
    "un poco más lejos del mic",
    "un poco más cerca",
    "más rápido",
    "más tranquilo / bajito",
    "tono normal otra vez",
]


def _open_input_stream(pa: pyaudio.PyAudio):
    """Abre el mic. Intenta 16kHz nativo; si el device no lo soporta, cae a 44.1k + resample."""
    for sr in (_TARGET_SR, 44100, 48000):
        try:
            stream = pa.open(
                format=_FMT, channels=_CHANNELS, rate=sr,
                input=True, frames_per_buffer=1024,
            )
            return stream, sr
        except Exception:
            continue
    raise RuntimeError("no pude abrir el mic en ningún sample rate")


def _record_one(stream, rec_sr: int) -> bytes:
    """Graba _REC_SECONDS y devuelve PCM 16-bit mono a _TARGET_SR."""
    frames = []
    n_chunks = int(rec_sr / 1024 * _REC_SECONDS)
    for _ in range(n_chunks):
        frames.append(stream.read(1024, exception_on_overflow=False))
    pcm = b"".join(frames)
    if rec_sr != _TARGET_SR:
        pcm, _ = audioop.ratecv(pcm, 2, _CHANNELS, rec_sr, _TARGET_SR, None)
    return pcm


def _rms_level(pcm: bytes) -> int:
    """Energía RMS para feedback (¿grabó algo o silencio?)."""
    return audioop.rms(pcm, 2)


def _save_wav(path: str, pcm: bytes) -> None:
    with wave.open(path, "wb") as w:
        w.setnchannels(_CHANNELS)
        w.setsampwidth(2)
        w.setframerate(_TARGET_SR)
        w.writeframes(pcm)


def main() -> None:
    n_target = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    os.makedirs(_OUT_DIR, exist_ok=True)

    existing = sorted(f for f in os.listdir(_OUT_DIR) if f.startswith("user_") and f.endswith(".wav"))
    start_idx = len(existing)
    if start_idx >= n_target:
        print(f"Ya hay {start_idx} grabaciones en {_OUT_DIR} (>= {n_target}). Nada que hacer.")
        print("Borrá el dir si querés regrabar de cero.")
        return

    print("=" * 60)
    print(f"  Grabación de 'hey saga' — {n_target} muestras (tenés {start_idx})")
    print("=" * 60)
    print("  Mic: el de la laptop (mismo que vas a usar).")
    print("  Cuando diga GRABÁ, decí 'hey saga' una vez, claro.")
    print("  Ctrl+C para cortar (lo grabado queda guardado).")
    print("=" * 60)

    pa = pyaudio.PyAudio()
    stream, rec_sr = _open_input_stream(pa)
    if rec_sr != _TARGET_SR:
        print(f"  (grabando a {rec_sr}Hz → resample a {_TARGET_SR}Hz)")
    print()

    try:
        for i in range(start_idx, n_target):
            tip = _TIPS[i % len(_TIPS)]
            print(f"[{i + 1}/{n_target}] {tip}")
            for c in ("3", "2", "1", "GRABÁ"):
                print(f"   {c} ", end="", flush=True)
                time.sleep(0.5)
            print()
            pcm = _record_one(stream, rec_sr)
            level = _rms_level(pcm)
            path = os.path.join(_OUT_DIR, f"user_{i:03d}.wav")
            _save_wav(path, pcm)
            bar = "#" * min(40, level // 80)
            warn = "  ⚠ MUY BAJO, repetí más fuerte/cerca" if level < 300 else ""
            print(f"   ✓ guardado (nivel: {bar or '.'}){warn}")
            print()
            time.sleep(0.3)
    except KeyboardInterrupt:
        print("\n\nCortado. Lo grabado quedó guardado.")
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()

    total = len([f for f in os.listdir(_OUT_DIR) if f.startswith("user_")])
    print("=" * 60)
    print(f"  Listo: {total} grabaciones en {_OUT_DIR}")
    print(f"  Siguiente: .venv/bin/python scripts/finetune_wakeword.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
