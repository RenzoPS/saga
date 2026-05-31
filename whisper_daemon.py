#!/usr/bin/env python3
"""Daemon STT de Whisper: modelo caliente en RAM, atiende por socket Unix.

voice_claude.py lo spawnea una vez (al empezar a grabar). transcribe() le manda
el path del wav y recibe el texto, sin pagar en CADA Win+Z ni el import de
faster_whisper ni la recarga del modelo (~3s). Se autoapaga tras IDLE_TIMEOUT_S
sin uso para no retener RAM indefinidamente en la APU.

Protocolo (newline-delimited JSON sobre AF_UNIX):
  req:  {"audio": "/tmp/voice-claude.wav", "lang": "es"}\n
  resp: {"ok": true, "text": "..."}\n  |  {"ok": false, "error": "..."}\n
"""

import os
import sys
import json
import time
import socket
from pathlib import Path

# params de decodificación compartidos con vc/ (una sola fuente, no duplicar).
# El daemon se spawnea como `python /abs/whisper_daemon.py` -> PROJECT_DIR queda en path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from vc.config import WHISPER_DECODE

SOCK_PATH = Path(os.environ.get("VOICE_WHISPER_SOCK", "/tmp/voice-claude-whisper.sock"))
MODEL_SIZE = os.environ.get("VOICE_WHISPER_SIZE", "small")
BEAM_SIZE = int(os.environ.get("VOICE_WHISPER_BEAM", "5"))
IDLE_TIMEOUT_S = float(os.environ.get("VOICE_WHISPER_IDLE", "1800"))  # 30 min
LOG_FILE = Path.home() / ".local/share/voice-claude/voice_claude.log"


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] whisperd: {msg}\n"
    sys.stderr.write(line)
    try:
        with LOG_FILE.open("a") as f:
            f.write(line)
    except OSError:
        pass


def transcribe(model, audio_path: str, lang: str) -> str:
    segments, _info = model.transcribe(
        audio_path,
        language=lang,
        beam_size=BEAM_SIZE,
        **WHISPER_DECODE,   # tuneado para ES, anti-alucinación (fuente única en vc/config)
    )
    return " ".join(s.text.strip() for s in segments).strip()


def main() -> int:
    # Anti doble-arranque: si el socket ya responde, hay otro daemon vivo.
    if SOCK_PATH.exists():
        try:
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            probe.settimeout(0.5)
            probe.connect(str(SOCK_PATH))
            probe.close()
            log("ya hay daemon vivo, salgo")
            return 0
        except OSError:
            SOCK_PATH.unlink(missing_ok=True)  # socket muerto -> limpio

    log(f"cargando modelo {MODEL_SIZE} (int8, cpu, beam={BEAM_SIZE})...")
    t0 = time.monotonic()
    from faster_whisper import WhisperModel

    model = WhisperModel(
        MODEL_SIZE,
        device="cpu",
        compute_type="int8",
        cpu_threads=4,  # 4 cores fisicos del Ryzen 5 3450U, SMT no ayuda en int8
    )
    log(f"modelo listo en {time.monotonic() - t0:.1f}s")

    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(SOCK_PATH))
    os.chmod(SOCK_PATH, 0o600)   # solo el dueño puede conectar (sin esto, cualquier user local entra)
    srv.listen(4)
    srv.settimeout(IDLE_TIMEOUT_S)
    log(f"escuchando en {SOCK_PATH} (idle {IDLE_TIMEOUT_S:.0f}s)")

    try:
        while True:
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                log("idle timeout, apago")
                return 0
            with conn:
                try:
                    conn.settimeout(60)
                    buf = b""
                    while b"\n" not in buf:
                        chunk = conn.recv(4096)
                        if not chunk:
                            break
                        buf += chunk
                    if not buf:
                        continue
                    req = json.loads(buf.split(b"\n", 1)[0].decode())
                    t1 = time.monotonic()
                    text = transcribe(model, req["audio"], req.get("lang", "es"))
                    log(f"transcribe {time.monotonic() - t1:.1f}s -> {text!r}")
                    conn.sendall((json.dumps({"ok": True, "text": text}) + "\n").encode())
                except Exception as e:
                    log(f"req error: {type(e).__name__}: {e}")
                    try:
                        conn.sendall(
                            (json.dumps({"ok": False, "error": str(e)}) + "\n").encode()
                        )
                    except OSError:
                        pass
    finally:
        SOCK_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
