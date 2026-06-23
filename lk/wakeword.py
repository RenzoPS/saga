"""Wake word detection local para saga.

Escucha 'hey saga' en background via portaudio (independiente del audio de LiveKit).
Al detectar la frase, llama on_wake() en el mismo event loop del agente.

Toggle: DESHABILITADO por default. Activar con SAGA_WAKE_ENABLED=1.
Modelo:  SAGA_WAKE_MODEL=<path> (default: models/hey_saga/hey_saga.onnx relativo al root).

Para generar el modelo: .venv/bin/python scripts/train_wakeword.py
Sistema requerido:     sudo pacman -S portaudio
"""

import asyncio
import os

from vc.runtime import log

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_MODEL = os.path.join(_ROOT, "models", "hey_saga", "hey_saga.onnx")


class WakeWordDetector:
    """Detector de wake word "hey saga" corriendo como tarea asyncio de fondo."""

    def __init__(
        self,
        on_wake,
        model_path: str | None = None,
        threshold: float = 0.92,
        debounce: float = 2.0,
    ):
        self._on_wake = on_wake
        self._model_path = model_path or os.environ.get("SAGA_WAKE_MODEL") or _DEFAULT_MODEL
        # SAGA_WAKE_THRESHOLD permite tunear sin tocar código (default 0.92).
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
        self._task = asyncio.create_task(self._run(), name="wakeword-listener")
        log(f"[wakeword] escuchando 'hey saga' (threshold={self._threshold}, debounce={self._debounce}s)")

    async def _run(self) -> None:
        from livekit.wakeword import WakeWordModel, WakeWordListener

        model = WakeWordModel(models=[self._model_path])
        try:
            async with WakeWordListener(
                model, threshold=self._threshold, debounce=self._debounce
            ) as listener:
                while True:
                    detection = await listener.wait_for_detection()
                    log(f"[wakeword] '{detection.name}' detectado (confianza={detection.confidence:.2f})")
                    try:
                        from vc.sound import play_beep
                        play_beep()
                    except Exception as e:
                        log(f"[wakeword] beep falló: {e}")
                    self._on_wake()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log(f"[wakeword] error en listener: {e}")

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        log("[wakeword] detenido")
