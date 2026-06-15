"""TTS custom de LiveKit con edge-tts (voz Elena AR, la misma del flujo actual).

edge-tts emite MP3 en stream; lo empujamos crudo al AudioEmitter declarando
mime_type="audio/mp3" -> LiveKit lo decodifica a PCM internamente (PyAV). Así no
perdemos la voz ni reescribimos el chunking/decoding a mano.
"""

from livekit.agents import tts, utils, APIConnectionError, DEFAULT_API_CONNECT_OPTIONS

from vc.config import EDGE_VOICE, EDGE_RATE, EDGE_PITCH

_SAMPLE_RATE = 24000  # edge-tts emite MP3 mono a 24 kHz


class EdgeTTS(tts.TTS):
    def __init__(self) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=_SAMPLE_RATE,
            num_channels=1,
        )

    def synthesize(
        self, text: str, *, conn_options=DEFAULT_API_CONNECT_OPTIONS
    ) -> "tts.ChunkedStream":
        return _EdgeChunkedStream(tts=self, input_text=text, conn_options=conn_options)


class _EdgeChunkedStream(tts.ChunkedStream):
    async def _run(self, output_emitter: "tts.AudioEmitter") -> None:
        import edge_tts

        output_emitter.initialize(
            request_id=utils.shortuuid(),
            sample_rate=_SAMPLE_RATE,
            num_channels=1,
            mime_type="audio/mp3",
        )
        communicate = edge_tts.Communicate(
            self._input_text, EDGE_VOICE, rate=EDGE_RATE, pitch=EDGE_PITCH
        )
        try:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio" and chunk.get("data"):
                    output_emitter.push(chunk["data"])
        except Exception as e:  # noqa: BLE001
            raise APIConnectionError() from e
        output_emitter.flush()
