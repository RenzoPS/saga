"""Síntesis de voz (TTS) y streaming. Limpieza de markdown, word-aliases,
microchunking de oraciones, y el pipeline edge-tts -> mpg123 -> pacat con
metering de nivel (RMS) que alimenta al orbe en tiempo real."""

import re
import json
import queue
import threading
import subprocess
import asyncio
from typing import Iterator

from .config import WORD_ALIASES_PATH, EDGE_VOICE, EDGE_RATE, EDGE_PITCH
from .runtime import log, _cancel


_WORD_ALIASES: "dict[str, str]" = {}
_WORD_ALIASES_RE: "re.Pattern | None" = None


def load_word_aliases() -> None:
    """Carga JSON con mappings palabra→fonetizacion. Editable por el user."""
    global _WORD_ALIASES, _WORD_ALIASES_RE
    if not WORD_ALIASES_PATH.exists():
        return
    try:
        data = json.loads(WORD_ALIASES_PATH.read_text())
        if not isinstance(data, dict):
            log(f"word_aliases: top-level no es dict, ignoro")
            return
        _WORD_ALIASES = {str(k).lower(): str(v) for k, v in data.items()}
        if _WORD_ALIASES:
            keys = sorted(_WORD_ALIASES.keys(), key=len, reverse=True)
            pattern = r"\b(" + "|".join(re.escape(k) for k in keys) + r")\b"
            _WORD_ALIASES_RE = re.compile(pattern, re.IGNORECASE)
            log(f"word_aliases loaded: {len(_WORD_ALIASES)} entries")
    except Exception as e:
        log(f"word_aliases load EXC: {type(e).__name__}: {e}")


def apply_word_aliases(text: str) -> str:
    if _WORD_ALIASES_RE is None:
        return text
    return _WORD_ALIASES_RE.sub(lambda m: _WORD_ALIASES[m.group(0).lower()], text)


def clean_for_tts(text: str) -> str:
    """Saca markdown que Edge TTS leeria literal. Edge maneja simbolos, paths,
    paréntesis, anglicismos y numeros por si solo - no hace falta limpiarlos."""
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"^\s*```[a-zA-Z0-9_+-]*\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"```", "", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"_([^_]+)_", r"\1", text)
    text = re.sub(r"~~([^~]+)~~", r"\1", text)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^>\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[\s]*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[\s]*\d+\.\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("*", "").replace("`", "")
    text = re.sub(r"\n{2,}", ". ", text)
    text = re.sub(r"\s+", " ", text)
    text = text.strip()
    return apply_word_aliases(text)   # fonetizaciones del JSON editable (no-op si no hay aliases)


_HARD_PUNCT_CHARS = ".!?¿¡…"
_MAX_BUFFERED_WORDS = 30  # safety cap, generalmente flushea por puntuacion semantica

# Si el siguiente chunk arranca con esto, NO flushar el buffer aunque haya hard punct
# (es continuacion: una oracion que sigue, no oracion nueva)
_CONTINUATION_RE = re.compile(
    r"^(y |o |pero |porque |es decir|por ejemplo|por ende|tipo |como |"
    r"así que|asi que|entonces |tambien|también |"
    r"además|ademas |sino |aunque |mientras |cuando |"
    r"para |de hecho|por eso|por cierto|igual |digamos)",
    re.IGNORECASE,
)


class TTSStreamer:
    """Pipeline edge-tts (online, Microsoft Neural) + mpg123 (decoder MP3 stream).
    Edge TTS soporta multilingue real -> pronuncia anglicismos correctamente.
    mpg123 acepta MP3 frames concatenados en stdin como stream continuo."""

    _SENTINEL = object()

    RATE = 24000
    BLK = 1024  # ~42.7ms por bloque

    def __init__(self) -> None:
        self._q: queue.Queue = queue.Queue()
        self._player: "subprocess.Popen | None" = None  # sink MP3 (decoder en chain, o mpg123 en fallback)
        self._play: "subprocess.Popen | None" = None     # reproductor PCM (pacat) en chain
        self._run = False
        self._pipe_lock = threading.Lock()
        self._sentence_buf: str = ""
        self._pending: str = ""
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _ensure_player(self) -> bool:
        """Reproductor simple: edge-tts -> mpg123 (decodifica y reproduce directo).
        Sin metering: el orbe anima stylized (no recibe nivel de audio), así no hay
        desfase posible entre el sonido (este proceso) y el dibujo (el browser)."""
        with self._pipe_lock:
            if self._player is not None and self._player.poll() is None:
                return True
            try:
                self._player = subprocess.Popen(
                    ["mpg123", "-q", "-"],
                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                self._play = None
                self._run = False
                log("tts player up (mpg123)")
                return True
            except Exception as e:
                log(f"mpg123 spawn EXC: {type(e).__name__}: {e}")
                return False

    def enqueue(self, sentence: str) -> None:
        if sentence.strip():
            self._q.put(sentence)

    def finish(self) -> None:
        self._q.put(self._SENTINEL)

    def wait(self, timeout: float = 120.0) -> None:
        self._thread.join(timeout=timeout)

    def cancel(self) -> None:
        """Drena cola, mata pipeline inmediato."""
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass
        self._q.put(self._SENTINEL)
        self._kill_pipeline()

    def _kill_pipeline(self) -> None:
        """Mata la cadena inmediato (SIGTERM -> SIGKILL fallback)."""
        self._run = False   # corta el pump ya
        with self._pipe_lock:
            player, play = self._player, self._play
            self._player = self._play = None
        for p in (player, play):
            if p is None or p.poll() is not None:
                continue
            try:
                p.terminate()
                try:
                    p.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    p.kill()
            except Exception as e:
                log(f"tts kill EXC: {type(e).__name__}: {e}")

    def _drain_pipeline(self) -> None:
        """Cierra stdin del decoder para EOF; el pump drena el PCM restante a pacat
        y cierra su stdin; esperamos que pacat termine de reproducir."""
        with self._pipe_lock:
            player, play = self._player, self._play
            self._player = self._play = None
        if player is None:
            self._run = False
            return
        try:
            if player.stdin and not player.stdin.closed:
                player.stdin.close()
        except Exception:
            pass
        try:
            player.wait(timeout=60)        # decoder termina de decodificar
        except subprocess.TimeoutExpired:
            player.terminate()
        if play is not None:
            try:
                play.wait(timeout=60)      # pacat termina de reproducir la cola
            except subprocess.TimeoutExpired:
                play.terminate()
        self._run = False

    @staticmethod
    def _should_flush_after(pending: str, next_chunk: str) -> bool:
        """Decide si flushar buffer despues de agregar `pending`, dado que `next_chunk` viene a continuacion.
        Solo flushea si `pending` cierra una oracion Y `next_chunk` no la continua."""
        if not pending.strip():
            return False
        last_char = pending.rstrip()[-1:]
        if last_char not in _HARD_PUNCT_CHARS:
            return False
        nxt = next_chunk.lstrip()
        if not nxt:
            return True
        if nxt[0].islower():
            return False
        if _CONTINUATION_RE.match(nxt):
            return False
        return True

    def _enqueue_to_buf(self, chunk: str) -> None:
        if not chunk:
            return
        if self._sentence_buf:
            self._sentence_buf += " " + chunk
        else:
            self._sentence_buf = chunk

    def _accept_chunk(self, text: str) -> None:
        """Acumula chunks con lookahead semantico. Solo flushea cuando una oracion
        cierra Y el siguiente chunk no la continua."""
        clean = clean_for_tts(text)
        if not clean:
            return

        if self._pending:
            self._enqueue_to_buf(self._pending)
            if self._should_flush_after(self._pending, clean):
                self._flush_buffer()
            self._pending = ""

        self._pending = clean

        total_words = len((self._sentence_buf + " " + self._pending).split())
        if total_words >= _MAX_BUFFERED_WORDS:
            self._enqueue_to_buf(self._pending)
            self._pending = ""
            self._flush_buffer()

    def _drain_pending_and_buffer(self) -> None:
        """Cierre de stream: meter pending al buffer y flush."""
        if self._pending:
            self._enqueue_to_buf(self._pending)
            self._pending = ""
        if self._sentence_buf.strip():
            self._flush_buffer()

    async def _synth_to_player_async(self, text: str) -> None:
        """Genera MP3 streaming con edge-tts y lo escribe al stdin de mpg123."""
        import edge_tts  # type: ignore  # import lazy
        communicate = edge_tts.Communicate(
            text, EDGE_VOICE, rate=EDGE_RATE, pitch=EDGE_PITCH
        )
        async for chunk in communicate.stream():
            if _cancel.is_set():
                return
            if chunk["type"] != "audio":
                continue
            data = chunk.get("data")
            if not data:
                continue
            with self._pipe_lock:
                player = self._player
            if player is None or player.stdin is None:
                return
            try:
                player.stdin.write(data)
                player.stdin.flush()
            except (BrokenPipeError, OSError) as e:
                log(f"tts stdin write EXC: {type(e).__name__}: {e}")
                return

    def _flush_buffer(self) -> None:
        """Sintetiza el buffer con edge-tts y lo pipea a mpg123 como stream MP3."""
        text = self._sentence_buf.strip()
        self._sentence_buf = ""
        if not text:
            return
        if not self._ensure_player():
            return
        log(f"edge utt: {text[:160]!r}")
        try:
            asyncio.run(self._synth_to_player_async(text))
        except Exception as e:
            log(f"edge synth EXC: {type(e).__name__}: {e}")

    def _loop(self) -> None:
        try:
            while True:
                item = self._q.get()
                if item is self._SENTINEL:
                    if not _cancel.is_set():
                        self._drain_pending_and_buffer()
                        self._drain_pipeline()
                    else:
                        self._pending = ""
                        self._sentence_buf = ""
                        self._kill_pipeline()
                    return
                if _cancel.is_set():
                    continue
                try:
                    self._accept_chunk(str(item))
                except Exception as e:
                    log(f"TTS worker EXC: {type(e).__name__}: {e}")
        except Exception as e:
            log(f"TTS loop FATAL: {type(e).__name__}: {e}")
            self._kill_pipeline()


_HARD_PUNCT_RE = re.compile(r"[.!?¿¡…]+(?:\s+|$)")
_SOFT_PUNCT_RE = re.compile(r"[,;:](?:\s+|$)")
_MAX_WORDS_PER_CHUNK = 10
_MIN_WORDS_AFTER_SOFT = 3


def _next_chunk_cut(buf: str) -> "int | None":
    """Decide donde cortar el buffer en un chunk pronunciable. Devuelve indice o None."""
    m = _HARD_PUNCT_RE.search(buf)
    if m:
        return m.end()

    word_count = len(buf.split())

    m_soft = _SOFT_PUNCT_RE.search(buf)
    if m_soft:
        words_before = len(buf[:m_soft.end()].split())
        if words_before >= _MIN_WORDS_AFTER_SOFT:
            return m_soft.end()

    if word_count >= _MAX_WORDS_PER_CHUNK:
        words = buf.split()
        idx = 0
        for w in words[:_MAX_WORDS_PER_CHUNK]:
            idx = buf.index(w, idx) + len(w)
        return idx

    return None


def stream_to_sentences(deltas: Iterator[str], streamer: "TTSStreamer") -> None:
    """Microchunking: empuja al TTS apenas hay un chunk pronunciable.
    Reglas (en orden): puntuacion fuerte > coma con minimo de palabras > limite duro de palabras."""
    buf = ""
    for delta in deltas:
        if _cancel.is_set():
            break
        buf += delta
        while True:
            cut = _next_chunk_cut(buf)
            if cut is None:
                break
            chunk = buf[:cut].strip()
            buf = buf[cut:]
            if chunk:
                streamer.enqueue(chunk)
    if buf.strip() and not _cancel.is_set():
        streamer.enqueue(buf.strip())
