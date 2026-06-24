"""Wake word detection "hey saga" sobre el track de audio de LiveKit (modo room).

El worker consume el track del mic del BROWSER (rtc.AudioStream) y corre el modelo Python
sobre él. Al detectar la frase, llama on_wake() en el mismo event loop del agente.

Toggle: DESHABILITADO por default. Activar con SAGA_WAKE_ENABLED=1.
Modelo:  SAGA_WAKE_MODEL=<path> (default: models/hey_saga/hey_saga.onnx relativo al root).

Para generar el modelo: .venv/bin/python scripts/train_wakeword.py
"""

import asyncio
import os

from vc.runtime import log

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_MODEL = os.path.join(_ROOT, "models", "hey_saga", "hey_saga.onnx")


class WakeWordTrackDetector:
    """Detector de wake word "hey saga" sobre un TRACK de audio de LiveKit (modo room).

    Consume un rtc.AudioStream sobre el track del mic del BROWSER -> corre en el worker headless.
    Replica la ventana deslizante de 2s del WakeWordListener nativo (portaudio), pero alimentada
    por el track en vez del mic local. Modelo stateless: predict() espera ~2s de audio 16kHz.

    El modelo es stateless: predict() espera ~2s de audio 16kHz. Acumulamos frames de 80ms en una
    deque (25 frames = 2s) y corremos predict cada PREDICT_EVERY frames (~240ms) en un executor
    (no bloquea el loop). Debounce anti doble-disparo, igual que el listener.
    """

    def __init__(
        self,
        track,
        on_wake,
        model_path: str | None = None,
        threshold: float = 0.92,
        debounce: float = 2.0,
    ):
        self._track = track
        self._on_wake = on_wake
        self._model_path = model_path or os.environ.get("SAGA_WAKE_MODEL") or _DEFAULT_MODEL
        env_thr = os.environ.get("SAGA_WAKE_THRESHOLD")
        self._threshold = float(env_thr) if env_thr else threshold
        self._debounce = debounce
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if not os.path.exists(self._model_path):
            log(f"[wakeword] modelo no encontrado: {self._model_path}")
            log("[wakeword] ejecutá: .venv/bin/python scripts/train_wakeword.py")
            return
        try:
            from vc.sound import ensure_beep
            ensure_beep()
        except Exception as e:
            log(f"[wakeword] no pude preparar beep: {e}")
        self._task = asyncio.create_task(self._run(), name="wakeword-track")
        log(f"[wakeword] escuchando 'hey saga' sobre el track (threshold={self._threshold}, debounce={self._debounce}s)")

    async def _run(self) -> None:
        from collections import deque
        import numpy as np
        from livekit import rtc
        from livekit.wakeword import WakeWordModel

        SAMPLE_RATE = 16000
        FRAME_MS = 80
        FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000           # 1280 (igual que el listener nativo)
        CHUNK_FRAMES = int(2.0 * SAMPLE_RATE / FRAME_SAMPLES)    # 25 frames = 2s (lo que espera predict)
        PREDICT_EVERY = 3                                        # ~240ms entre predicts (menos CPU; el wake dura ~1s)

        model = WakeWordModel(models=[self._model_path])
        loop = asyncio.get_running_loop()
        buf: "deque[np.ndarray]" = deque(maxlen=CHUNK_FRAMES)
        since = 0
        last_det = 0.0
        # frame_size_ms=80 -> el stream resamplea el track a 16kHz mono y entrega frames de 1280 samples.
        stream = rtc.AudioStream.from_track(
            track=self._track, sample_rate=SAMPLE_RATE, num_channels=1, frame_size_ms=FRAME_MS,
        )
        try:
            async for ev in stream:
                buf.append(np.frombuffer(ev.frame.data, dtype=np.int16))
                since += 1
                if len(buf) < CHUNK_FRAMES or since < PREDICT_EVERY:
                    continue
                since = 0
                chunk = np.concatenate(list(buf))
                scores = await loop.run_in_executor(None, model.predict, chunk)
                if not scores:
                    continue
                name = max(scores, key=scores.get)
                if scores[name] >= self._threshold:
                    now = loop.time()
                    if now - last_det >= self._debounce:
                        last_det = now
                        buf.clear()   # descartar el audio del disparo -> no re-evalúa la misma frase
                        log(f"[wakeword] '{name}' detectado sobre el track (confianza={scores[name]:.2f})")
                        try:
                            from vc.sound import play_beep
                            play_beep()
                        except Exception as e:
                            log(f"[wakeword] beep falló: {e}")
                        self._on_wake()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log(f"[wakeword] error en el detector sobre el track: {e}")
        finally:
            try:
                await stream.aclose()
            except Exception:
                pass

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        log("[wakeword] (track) detenido")
