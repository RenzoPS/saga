"""Spike LiveKit: el runtime de audio (captura, streaming, chunks, VAD, turn
detection, barge-in) lo maneja livekit-agents. Claude Code sigue siendo el cerebro
(envuelto como LLM custom). Whisper y edge-tts se reusan como plugins STT/TTS.
NO reemplaza al flujo vc/ todavía: es un camino paralelo (rama livekit-spike)."""
