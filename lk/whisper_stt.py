"""STT custom de LiveKit con faster-whisper local (no-streaming).

Recibe el buffer de audio de un turno (LiveKit ya hizo VAD + turn detection) y lo
transcribe de una. Se envuelve con `stt.StreamAdapter(vad)` en agent.py para darle
semántica de streaming. Reusa los params de decodificación de `vc.config.WHISPER_DECODE`
(fuente única, los mismos del daemon/fallback del flujo actual).

OJO: en este modo LiveKit es dueño del audio -> el whisper_daemon de vc/ NO corre acá;
el modelo se carga caliente dentro de este proceso.
"""

import asyncio

import numpy as np
from livekit import rtc
from livekit.agents import stt, DEFAULT_API_CONNECT_OPTIONS
from livekit.agents.utils import AudioBuffer

from vc.config import WHISPER_SIZE, WHISPER_BEAM, WHISPER_DECODE

_TARGET_SR = 16000  # faster-whisper espera 16 kHz mono


def _to_whisper_array(buffer: AudioBuffer) -> np.ndarray:
    """AudioBuffer (lista de frames) -> float32 mono 16 kHz en [-1, 1]."""
    frame = rtc.combine_audio_frames(buffer)
    data = np.frombuffer(frame.data, dtype=np.int16).astype(np.float32) / 32768.0
    if frame.num_channels > 1:
        data = data.reshape(-1, frame.num_channels).mean(axis=1)
    if frame.sample_rate != _TARGET_SR and data.size:
        # Resample lineal (suficiente para STT; evita dep extra). El AudioFrame de
        # livekit-rtc no expone resample propio en esta versión.
        n_out = int(round(data.size * _TARGET_SR / frame.sample_rate))
        if n_out > 0:
            x_old = np.linspace(0.0, 1.0, data.size, endpoint=False)
            x_new = np.linspace(0.0, 1.0, n_out, endpoint=False)
            data = np.interp(x_new, x_old, data).astype(np.float32)
    return data


class WhisperSTT(stt.STT):
    def __init__(self) -> None:
        super().__init__(
            capabilities=stt.STTCapabilities(streaming=False, interim_results=False)
        )
        from faster_whisper import WhisperModel

        self._model = WhisperModel(
            WHISPER_SIZE, device="cpu", compute_type="int8", cpu_threads=4
        )

    async def _recognize_impl(
        self, buffer: AudioBuffer, *, language=None, conn_options=DEFAULT_API_CONNECT_OPTIONS
    ) -> "stt.SpeechEvent":
        samples = _to_whisper_array(buffer)

        def _run() -> str:
            segments, _info = self._model.transcribe(
                samples,
                language="es",
                beam_size=WHISPER_BEAM,
                **WHISPER_DECODE,
            )
            return " ".join(s.text.strip() for s in segments).strip()

        text = await asyncio.to_thread(_run)
        return stt.SpeechEvent(
            type=stt.SpeechEventType.FINAL_TRANSCRIPT,
            alternatives=[stt.SpeechData(language="es", text=text)],
        )
