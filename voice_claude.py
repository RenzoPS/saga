#!/usr/bin/env python3
"""voz -> Claude Code -> voz. Toggle por hotkey. Cancelable."""

import os
import re
import sys
import json
import queue
import base64
import asyncio
import uuid as uuid_lib
import signal
import time
import wave
import socket
import threading
import subprocess
import http.client
import urllib.request
from pathlib import Path
from typing import Callable, Iterator

import numpy as np
import sounddevice as sd

HOME = Path.home()
PROJECT_DIR = HOME / ".local/share/voice-claude"
PID_FILE = Path("/tmp/voice-claude.pid")
LOCK_FILE = Path("/tmp/voice-claude.lock")
AUDIO_FILE = Path("/tmp/voice-claude.wav")
OUT_WAV = Path("/tmp/voice-claude-out.wav")
LOG_FILE = PROJECT_DIR / "voice_claude.log"

EDGE_VOICE = "es-AR-ElenaNeural"  # Microsoft Edge TTS, voz argentina femenina
EDGE_RATE = "+5%"  # ligeramente mas rapida
EDGE_PITCH = "+0Hz"
WHISPER_SIZE = "small"
WHISPER_BEAM = 5  # beam search amplio: evita loops de alucinacion (greedy/beam1 los dispara)
# Daemon STT: mantiene el modelo caliente en RAM entre invocaciones (mata los ~3s
# de recarga por Win+Z). transcribe() es cliente; si el daemon esta caido cae a inline.
WHISPER_SOCK = Path("/tmp/voice-claude-whisper.sock")
WHISPER_DAEMON = PROJECT_DIR / "whisper_daemon.py"
WHISPER_IDLE_S = 1800  # daemon se autoapaga tras 30 min sin uso
CLAUDE_MODEL = "haiku"
# Saltar permisos de Claude (modo dios). Default ON para no romper el flujo actual;
# exportá VOICE_CLAUDE_SAFE=1 para correr en modo seguro (Claude pide permisos).
CLAUDE_SKIP_PERMISSIONS = os.environ.get("VOICE_CLAUDE_SAFE") != "1"

# Arranque liviano del CLI -> primer token MUCHO mas rapido (de ~57s a ~7s).
# Mata lo que el voice-assistant no necesita y arrancaba en CADA Win+Z:
#  - MCP servers pesados (playwright lanzaba un Chromium, npx bajaba paquetes, Google MCPs timeouteaban)
#  - resto de plugins/hooks/skills (caveman, superpowers, context-mode) via --setting-sources ''
# Mantiene claude-mem COMPLETO (recall + captura + hooks + su MCP) via --plugin-dir.
# (Verificado: corre el worker + chroma, sin costo extra de latencia.)
# La personalidad viene de --append-system-prompt; el login OAuth queda intacto; tools built-in intactos.
# OJO: si claude-mem se actualiza, cambiar el numero de version del path.
CLAUDE_MEM_DIR = "/home/renzo/.claude/plugins/cache/thedotmack/claude-mem/13.4.0"
CLAUDE_FAST_FLAGS = [
    "--plugin-dir", CLAUDE_MEM_DIR,
    "--setting-sources", "",
    "--disable-slash-commands",
]
SAMPLE_RATE = 16000
CHANNELS = 1
MIN_DURATION_S = 0.4
CLAUDE_TIMEOUT_S = 180

MONITOR_CLASS = "voice-claude-monitor"
MONITOR_WORKSPACE = 10

SCREENSHOT_PATH = Path("/tmp/voice-claude-screenshot.png")

# Orbe visual: reemplaza las notificaciones. Server SSE persistente en localhost,
# la pagina (orb/orb.html) se sincroniza en vivo con la fase actual.
ORB_DIR = PROJECT_DIR / "orb"
ORB_PORT = int(os.environ.get("ORB_PORT", "8777"))
ORB_URL = f"http://127.0.0.1:{ORB_PORT}/"
ORB_SERVER = ORB_DIR / "orb_server.py"

# Diccionario de palabras-problema. Se carga al iniciar desde JSON editable.
# Se aplica con word boundary regex en clean_for_tts antes de mandar a piper.
WORD_ALIASES_PATH = PROJECT_DIR / "word_aliases.json"

SESSION_FILE = PROJECT_DIR / "session.json"

# Regex que matchea CUALQUIER mencion visual como palabra suelta.
# Usa word boundaries para evitar falsos positivos (ej "admira" no matchea "mira").
VISUAL_RE = re.compile(
    r"\b("
    # verbos mirar / fijate (cualquier conjugacion comun)
    r"mira|mirá|mirar|miralo|míralo|miremos|"
    r"fijate|fíjate|fijensé|"
    # verbos ver / mostrar
    r"ves|podes ver|podés ver|puedes ver|"
    r"estoy viendo|estoy mirando|"
    r"mostrarte|mostrar|muestro|mostrame|"
    # referencias a pantalla
    r"pantalla|"
    # locativos + en
    r"aca en|acá en|aqui en|aquí en|"
    # opinar/parecer + demostrativo presente
    r"te parece esto|te parece este|te parece esta|"
    r"te parece aca|te parece acá|te parece aqui|te parece aquí|"
    r"te parece mi|"
    r"opinas de esto|opinás de esto|"
    r"pensas de esto|pensás de esto"
    r")\b",
    re.IGNORECASE,
)


# Frases que disparan reset manual de la sesion conversacional.
RESET_KEYWORDS = (
    "nueva sesion",
    "nueva sesión",
    "nueva conversacion",
    "nueva conversación",
    "borra la conversacion",
    "borra la conversación",
    "empezamos de cero",
    "olvidate de todo",
    "olvídate de todo",
    "olvida todo",
    "reseteá la sesión",
    "resetear sesion",
    "resetear sesión",
)

# Mutable state para cancelacion global desde signal handler.
_cancel = threading.Event()
_current_proc: subprocess.Popen | None = None
_proc_lock = threading.Lock()
_current_streamer: "TTSStreamer | None" = None
_streamer_lock = threading.Lock()


def log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}\n"
    sys.stderr.write(line)
    try:
        with LOG_FILE.open("a") as f:
            f.write(line)
    except OSError:
        pass


def hypr_notify(msg: str, color: str = "rgb(33aaff)", ms: int = 3000, icon: int = -1) -> None:
    subprocess.Popen(
        ["hyprctl", "notify", str(icon), str(ms), color, msg],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def hypr_dismiss(n: int = 1) -> None:
    subprocess.Popen(
        ["hyprctl", "dismissnotify", str(n)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def hypr_dismiss_all() -> None:
    subprocess.Popen(
        ["hyprctl", "dismissnotify"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _orb_up() -> bool:
    try:
        urllib.request.urlopen(ORB_URL + "healthz", timeout=0.4)
        return True
    except Exception:
        return False


def ensure_orb() -> None:
    """Levanta el server del orbe si no corre y abre la pestaña esa primera vez."""
    if _orb_up():
        return
    try:
        subprocess.Popen(
            [sys.executable, str(ORB_SERVER)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env={**os.environ, "ORB_PORT": str(ORB_PORT)},
        )
    except OSError as e:
        log(f"orb spawn fail: {e}")
        return
    for _ in range(25):
        if _orb_up():
            break
        time.sleep(0.1)
    # server recien levantado -> abrir pestaña una vez
    try:
        subprocess.Popen(
            ["xdg-open", ORB_URL],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as e:
        log(f"xdg-open fail: {e}")


class _OrbClient:
    """Sender persistente y NO bloqueante hacia el orbe.

    - Estados por cola confiable (no se pierden).
    - Nivel coalescado (ultimo valor) y rate-cap ~15Hz (bateria/latencia).
    - Una sola conexion HTTP keep-alive; los callers nunca bloquean en red.
    """

    LEVEL_HZ = 33.0   # alto para no perder el envelope de las silabas (sync TTS)

    def __init__(self) -> None:
        self._q: queue.Queue = queue.Queue(maxsize=64)
        self._lock = threading.Lock()
        self._level: "float | None" = None
        self._conn: "http.client.HTTPConnection | None" = None
        self._started = False

    def _ensure_thread(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        threading.Thread(target=self._loop, daemon=True).start()

    def state(self, name: str) -> None:
        self._ensure_thread()
        try:
            self._q.put_nowait(name)
        except queue.Full:
            pass

    def level(self, v: float) -> None:
        self._ensure_thread()
        with self._lock:
            self._level = v

    def _post(self, path: str) -> None:
        for attempt in (1, 2):
            try:
                if self._conn is None:
                    self._conn = http.client.HTTPConnection("127.0.0.1", ORB_PORT, timeout=0.5)
                self._conn.request("POST", path, body=b"")
                self._conn.getresponse().read()
                return
            except Exception:
                try:
                    if self._conn:
                        self._conn.close()
                except Exception:
                    pass
                self._conn = None  # reconecta en el proximo intento

    def _loop(self) -> None:
        min_dt = 1.0 / self.LEVEL_HZ
        last_level = 0.0
        while True:
            try:
                name = self._q.get(timeout=0.05)
                self._post(f"/state?s={name}")
            except queue.Empty:
                pass
            now = time.monotonic()
            if now - last_level >= min_dt:
                with self._lock:
                    lv = self._level
                    self._level = None
                if lv is not None:
                    self._post(f"/level?v={lv:.3f}")
                    last_level = now


_orb = _OrbClient()


def orb_state(name: str) -> None:
    _orb.state(name)


def orb_level(v: float) -> None:
    _orb.level(v)


def take_screenshot() -> Path | None:
    """Captura pantalla con grim. Devuelve path o None si fallo."""
    try:
        result = subprocess.run(
            ["grim", str(SCREENSHOT_PATH)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            log(f"grim FAIL rc={result.returncode} stderr={result.stderr[:200]}")
            return None
        if not SCREENSHOT_PATH.exists() or SCREENSHOT_PATH.stat().st_size == 0:
            return None
        size_kb = SCREENSHOT_PATH.stat().st_size // 1024
        log(f"screenshot saved {size_kb}KB")
        return SCREENSHOT_PATH
    except Exception as e:
        log(f"grim EXC: {type(e).__name__}: {e}")
        return None


def ensure_monitor_open() -> None:
    """Abre kitty con tail del log en workspace MONITOR_WORKSPACE si no esta abierta."""
    try:
        clients = subprocess.check_output(
            ["hyprctl", "clients"], text=True, timeout=2
        )
        if MONITOR_CLASS in clients:
            return
    except Exception as e:
        log(f"hyprctl clients fail: {type(e).__name__}: {e}")
    cmd = (
        f"[workspace {MONITOR_WORKSPACE}] "
        f"kitty --class {MONITOR_CLASS} --title 'voice-claude monitor' "
        f"-e tail -n 80 -F {LOG_FILE}"
    )
    subprocess.Popen(
        ["hyprctl", "dispatch", "exec", cmd],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    log(f"monitor kitty spawned on ws{MONITOR_WORKSPACE}")


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def read_pid_from(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        pid = int(path.read_text().strip())
    except (ValueError, OSError):
        path.unlink(missing_ok=True)
        return None
    if not pid_alive(pid):
        path.unlink(missing_ok=True)
        return None
    return pid


def read_recorder_pid() -> int | None:
    return read_pid_from(PID_FILE)


def read_owner_pid() -> int | None:
    return read_pid_from(LOCK_FILE)


def signal_stop(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGUSR1)
    except ProcessLookupError:
        PID_FILE.unlink(missing_ok=True)


def signal_cancel(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGUSR2)
    except ProcessLookupError:
        LOCK_FILE.unlink(missing_ok=True)


def set_current_proc(proc: subprocess.Popen | None) -> None:
    global _current_proc
    with _proc_lock:
        _current_proc = proc


def kill_current_proc() -> None:
    """SIGTERM primero (chance de cleanup), SIGKILL si no muere en 1s."""
    with _proc_lock:
        p = _current_proc
    if p is None or p.poll() is not None:
        return
    try:
        p.terminate()
    except ProcessLookupError:
        return
    except Exception as e:
        log(f"terminate EXC: {type(e).__name__}: {e}")
        return
    try:
        p.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        log("terminate ignored, sending SIGKILL")
        try:
            p.kill()
        except Exception:
            pass


def cancel_handler(_sig, _frame):
    log("ABORT signal received (SIGUSR2)")
    _cancel.set()
    kill_current_proc()
    cancel_streamer()


def record_until_signaled() -> float:
    PID_FILE.write_text(str(os.getpid()))
    stop_event = threading.Event()

    def handler(_sig, _frame):
        stop_event.set()

    signal.signal(signal.SIGUSR1, handler)
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

    orb_state("rec")
    log("rec start")

    buf: list[np.ndarray] = []
    mic_level = [0.0]

    def callback(indata, _frames, _t, _status):
        buf.append(indata.copy())
        a = indata.astype(np.float32) / 32768.0
        mic_level[0] = min(1.0, float(np.sqrt(np.mean(a * a))) * 5.0) if a.size else 0.0

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="int16",
        callback=callback,
    ):
        while not stop_event.is_set() and not _cancel.is_set():
            time.sleep(0.05)
            orb_level(mic_level[0])   # nivel real del mic -> orbe late con tu voz

    log(f"rec stop. chunks={len(buf)}")
    if not buf:
        return 0.0

    audio = np.concatenate(buf)
    with wave.open(str(AUDIO_FILE), "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(audio.tobytes())
    duration = len(audio) / SAMPLE_RATE
    log(f"wav saved {AUDIO_FILE} duration={duration:.2f}s")
    return duration


def _whisper_daemon_up() -> bool:
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.3)
        s.connect(str(WHISPER_SOCK))
        s.close()
        return True
    except OSError:
        return False


def prewarm_whisper() -> None:
    """Spawnea el daemon de Whisper si no corre. NO bloquea: el modelo carga en
    paralelo mientras el usuario graba, asi transcribe() no paga la recarga."""
    if _whisper_daemon_up():
        return
    try:
        subprocess.Popen(
            [sys.executable, str(WHISPER_DAEMON)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env={
                **os.environ,
                "VOICE_WHISPER_SOCK": str(WHISPER_SOCK),
                "VOICE_WHISPER_SIZE": WHISPER_SIZE,
                "VOICE_WHISPER_BEAM": str(WHISPER_BEAM),
                "VOICE_WHISPER_IDLE": str(WHISPER_IDLE_S),
            },
        )
        log("whisper daemon spawned (prewarm)")
    except OSError as e:
        log(f"whisper daemon spawn fail: {e}")


def _transcribe_via_daemon(timeout_s: float = 90.0) -> str | None:
    """Pide la transcripcion al daemon. Devuelve texto, o None si no se pudo
    (para caer al fallback inline). Espera hasta timeout_s a que el modelo
    termine de cargar si recien se spawneo (carga en paralelo a la grabacion)."""
    deadline = time.monotonic() + timeout_s
    conn = None
    while time.monotonic() < deadline:
        if _cancel.is_set():
            return None
        try:
            conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            conn.settimeout(timeout_s)
            conn.connect(str(WHISPER_SOCK))
            break
        except OSError:
            conn = None
            time.sleep(0.15)
    if conn is None:
        return None
    try:
        conn.sendall((json.dumps({"audio": str(AUDIO_FILE), "lang": "es"}) + "\n").encode())
        buf = b""
        while b"\n" not in buf:
            chunk = conn.recv(4096)
            if not chunk:
                break
            buf += chunk
        if not buf:
            return None
        resp = json.loads(buf.split(b"\n", 1)[0].decode())
        if not resp.get("ok"):
            log(f"whisper daemon error: {resp.get('error')}")
            return None
        return resp.get("text", "")
    except Exception as e:
        log(f"whisper daemon req fail: {type(e).__name__}: {e}")
        return None
    finally:
        try:
            conn.close()
        except OSError:
            pass


def _transcribe_inline() -> str:
    """Fallback: carga el modelo en este proceso (lento, paga ~3s) si el daemon
    no esta disponible. Garantiza que el voice-assistant nunca quede mudo."""
    log("whisper fallback inline (carga modelo)")
    from faster_whisper import WhisperModel

    model = WhisperModel(
        WHISPER_SIZE,
        device="cpu",
        compute_type="int8",
        cpu_threads=4,  # 4 cores fisicos del Ryzen 5 3450U, SMT no ayuda en ML int8
    )
    segments, _info = model.transcribe(
        str(AUDIO_FILE),
        language="es",
        beam_size=WHISPER_BEAM,
        vad_filter=True,
        condition_on_previous_text=False,
        temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],  # fallback: reintenta si sale repetitivo/baja confianza
        compression_ratio_threshold=2.4,
        log_prob_threshold=-1.0,
        no_speech_threshold=0.6,
        no_repeat_ngram_size=3,  # prohíbe repetir trigramas -> mata loops "a ir a ir a ir"
    )
    return " ".join(s.text.strip() for s in segments).strip()


def transcribe() -> str:
    log("whisper transcribe (daemon)")
    text = _transcribe_via_daemon()
    if text is None:
        text = _transcribe_inline()
    log(f"whisper out: {text!r}")
    return text


def _new_session_id() -> str:
    sid = str(uuid_lib.uuid4())
    SESSION_FILE.write_text(json.dumps({"id": sid, "last_used": time.time()}))
    log(f"session new -> {sid}")
    return sid


def get_active_session_id() -> tuple[str, bool]:
    """Devuelve (uuid, is_new). is_new=True si recien generado (no existe en Claude todavia).
    No hay timeout automatico: la sesion persiste hasta que el usuario pida reset por voz."""
    if SESSION_FILE.exists():
        try:
            data = json.loads(SESSION_FILE.read_text())
            sid = str(data["id"])
            log(f"session use -> {sid}")
            return sid, False
        except (json.JSONDecodeError, KeyError, ValueError, OSError) as e:
            log(f"session file corrupt: {e}, rotate")
    return _new_session_id(), True


def touch_session() -> None:
    if not SESSION_FILE.exists():
        return
    try:
        data = json.loads(SESSION_FILE.read_text())
        data["last_used"] = time.time()
        SESSION_FILE.write_text(json.dumps(data))
    except (json.JSONDecodeError, KeyError, OSError):
        pass


def reset_session() -> str:
    return _new_session_id()


def is_reset_command(text: str) -> bool:
    norm = text.lower().strip().rstrip(".,!?¿¡ ")
    return any(k in norm for k in RESET_KEYWORDS)


def is_visual_command(text: str) -> bool:
    """Detecta si el prompt referencia algo que el usuario esta viendo en pantalla."""
    return VISUAL_RE.search(text) is not None


def ask_claude_stream(
    prompt: str,
    on_first_token: Callable[[], None] | None = None,
    screenshot_path: Path | None = None,
) -> Iterator[str]:
    """Stream text_delta events de Claude CLI. Maneja --resume/--session-id fallback.
    Si screenshot_path es dado, manda imagen + texto via --input-format stream-json."""
    has_image = screenshot_path is not None and screenshot_path.exists()
    log(f"claude prompt{' [+img]' if has_image else ''}: {prompt!r}")
    system = (
        "Estas hablando, no escribiendo. Tu respuesta sale por parlante (TTS multilingue "
        "que pronuncia bien anglicismos, numeros, simbolos y siglas; no te preocupes por fonetizar). "
        "\n\n"
        "Reglas firmes:\n"
        "- Texto plano. Nada de markdown: sin asteriscos, sin backticks, sin listas con guiones o numeros, sin headers.\n"
        "- Espanol rioplatense: vos, dale, che, fijate.\n"
        "- Largo proporcional: pregunta corta = respuesta corta. Tono conversacional, directo, sin floreos.\n"
        "- Si no podes responder por falta de datos o tools, una sola frase corta. No listes alternativas ni te disculpes.\n"
        "\n"
        "Estilo:\n"
        "Hablas como si le contaras algo a un amigo en un cafe. Nada de 'primero, segundo, tercero', "
        "'aspectos clave', 'puntos importantes', 'cabe destacar'. Frases fluidas, conectadas. "
        "Conectores naturales: 'asi que', 'entonces', 'igual', 'mira', 'fijate'. "
        "Si explicas algo tecnico, lo contas como historia, no como manual."
    )
    session_id, is_new = get_active_session_id()
    first_flag = "--session-id" if is_new else "--resume"
    second_flag = "--resume" if is_new else "--session-id"

    # Si hay imagen, pre-armo el JSON multimodal para stdin.
    stdin_payload: str | None = None
    if has_image:
        assert screenshot_path is not None
        try:
            img_bytes = screenshot_path.read_bytes()
            img_b64 = base64.b64encode(img_bytes).decode("ascii")
            stdin_payload = (
                json.dumps(
                    {
                        "type": "user",
                        "message": {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/png",
                                        "data": img_b64,
                                    },
                                },
                                {"type": "text", "text": prompt},
                            ],
                        },
                    }
                )
                + "\n"
            )
        except Exception as e:
            log(f"image encode EXC: {type(e).__name__}: {e}, falling back to text-only")
            has_image = False
            stdin_payload = None

    def _spawn(flag: str) -> subprocess.Popen:
        args = [
            "claude",
            "--model",
            CLAUDE_MODEL,
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--append-system-prompt",
            system,
            flag,
            session_id,
        ]
        args.extend(CLAUDE_FAST_FLAGS)
        if CLAUDE_SKIP_PERMISSIONS:
            args.append("--dangerously-skip-permissions")
        if has_image:
            args.extend(["-p", "--input-format", "stream-json"])
            return subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        args.extend(["-p", prompt])
        return subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    for attempt, flag in enumerate((first_flag, second_flag)):
        try:
            proc = _spawn(flag)
        except FileNotFoundError:
            log("claude FATAL: binary not found in PATH")
            return
        except Exception as e:
            log(f"claude SPAWN EXC: {type(e).__name__}: {e}")
            return

        set_current_proc(proc)
        # Si hay stdin payload (modo imagen), escribirlo y cerrar stdin.
        if stdin_payload is not None and proc.stdin is not None:
            try:
                proc.stdin.write(stdin_payload)
                proc.stdin.flush()
                proc.stdin.close()
            except Exception as e:
                log(f"stdin write EXC: {type(e).__name__}: {e}")
        text_received = False
        try:
            assert proc.stdout is not None
            deadline = time.time() + CLAUDE_TIMEOUT_S
            for raw_line in proc.stdout:
                if _cancel.is_set():
                    log("stream cancelled, breaking")
                    break
                if time.time() > deadline:
                    log(f"claude STREAM TIMEOUT after {CLAUDE_TIMEOUT_S}s")
                    break
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") != "stream_event":
                    continue
                event = obj.get("event", {})
                if event.get("type") != "content_block_delta":
                    continue
                delta = event.get("delta", {})
                if delta.get("type") != "text_delta":
                    continue
                text = delta.get("text", "")
                if text:
                    if not text_received:
                        if on_first_token is not None:
                            try:
                                on_first_token()
                            except Exception:
                                pass
                        text_received = True
                    yield text

            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
        finally:
            set_current_proc(None)

        if _cancel.is_set():
            return

        err = ""
        try:
            if proc.stderr is not None:
                err = proc.stderr.read() or ""
        except Exception:
            pass

        if proc.returncode == 0 and text_received:
            touch_session()
            log("claude stream done OK")
            return

        log(f"claude stream err rc={proc.returncode} flag={flag} stderr={err[:400]} text_received={text_received}")
        low = err.lower()
        retryable = (
            "no conversation found" in low
            or "not found" in low
            or "does not exist" in low
            or "already in use" in low
        )
        if attempt == 0 and retryable:
            log(f"retry stream with {second_flag}")
            continue
        return


_WORD_ALIASES: dict[str, str] = {}
_WORD_ALIASES_RE: re.Pattern | None = None


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
            # Regex case-insensitive word boundary para reemplazos seguros.
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
    # Bloques de codigo enteros (cerrados en el mismo chunk): quitar.
    text = re.sub(r"```[\s\S]*?```", "", text)
    # Fences sueltos (abren o cierran un bloque partido entre chunks): linea entera fuera.
    text = re.sub(r"^\s*```[a-zA-Z0-9_+-]*\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"```", "", text)
    # Markdown inline (preservar el contenido, sacar marcadores).
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
    # Caracteres residuales de markdown que pueden colarse
    text = text.replace("*", "").replace("`", "")

    # Collapse newlines/whitespace
    text = re.sub(r"\n{2,}", ". ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


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
        self._player: subprocess.Popen | None = None  # sink MP3 (decoder en chain, o mpg123 en fallback)
        self._play: subprocess.Popen | None = None     # reproductor PCM (pacat) en chain
        self._run = False
        self._pipe_lock = threading.Lock()
        self._sentence_buf: str = ""
        self._pending: str = ""
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _ensure_player(self) -> bool:
        """Cadena: mpg123 (decode->PCM) -> python (mide RMS) -> pacat (reproduce).
        El nivel sale al ritmo real de reproduccion -> el orbe late SINCRONIZADO.
        Fallback: mpg123 reproduce directo (sin metering) si la cadena no arranca."""
        with self._pipe_lock:
            if self._player is not None and self._player.poll() is None:
                return True
            try:
                dec = subprocess.Popen(
                    ["mpg123", "-q", "-s", "--mono", "-r", str(self.RATE), "-"],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                )
                play = subprocess.Popen(
                    ["pacat", "--format=s16le", f"--rate={self.RATE}",
                     "--channels=1", "--latency-msec=30"],   # buffer chico -> el nivel no adelanta al sonido
                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                self._player, self._play, self._run = dec, play, True
                threading.Thread(target=self._pump, args=(dec.stdout, play), daemon=True).start()
                log("tts player up (mpg123 -> pacat, metered)")
                return True
            except Exception as e:
                log(f"tts chain spawn EXC: {type(e).__name__}: {e}; fallback mpg123 directo")
            try:
                self._player = subprocess.Popen(
                    ["mpg123", "-q", "-"],
                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                self._play, self._run = None, False
                return True
            except Exception as e:
                log(f"mpg123 spawn EXC: {type(e).__name__}: {e}")
                return False

    def _pump(self, out, play) -> None:
        """Lee PCM del decoder, mide RMS (-> orbe) y lo manda a pacat. pacat consume
        a tiempo real -> esta lectura queda paceada a tiempo real -> nivel sincronizado."""
        try:
            while self._run:
                raw = out.read(self.BLK * 2)
                if not raw:
                    break
                a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                rms = float(np.sqrt(np.mean(a * a))) if a.size else 0.0
                orb_level(min(1.0, rms * 4.0))
                try:
                    play.stdin.write(raw)
                except (BrokenPipeError, OSError):
                    break
        finally:
            self._run = False
            try:
                if play.stdin:
                    play.stdin.close()
            except Exception:
                pass
            orb_level(0.0)

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
        orb_level(0.0)

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
        # `pending` termina con hard punct. Verificar continuacion.
        nxt = next_chunk.lstrip()
        if not nxt:
            return True
        # Si arranca con minuscula -> continuacion implicita.
        if nxt[0].islower():
            return False
        # Si arranca con conjunctor de continuacion conocido.
        if _CONTINUATION_RE.match(nxt):
            return False
        # OK, hard punct + sin senal de continuacion -> flush.
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

        # Procesar pending anterior usando `clean` como lookahead.
        if self._pending:
            self._enqueue_to_buf(self._pending)
            if self._should_flush_after(self._pending, clean):
                self._flush_buffer()
            self._pending = ""

        self._pending = clean

        # Safety: si buffer + pending pasan _MAX_BUFFERED_WORDS, flush forzado.
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
                        # Drenar pending + buffer pendiente antes de cerrar pipeline.
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


def set_current_streamer(s: "TTSStreamer | None") -> None:
    global _current_streamer
    with _streamer_lock:
        _current_streamer = s


def cancel_streamer() -> None:
    with _streamer_lock:
        s = _current_streamer
    if s is not None:
        s.cancel()


_HARD_PUNCT_RE = re.compile(r"[.!?¿¡…]+(?:\s+|$)")
_SOFT_PUNCT_RE = re.compile(r"[,;:](?:\s+|$)")
_MAX_WORDS_PER_CHUNK = 10
_MIN_WORDS_AFTER_SOFT = 3


def _next_chunk_cut(buf: str) -> int | None:
    """Decide donde cortar el buffer en un chunk pronunciable. Devuelve indice o None."""
    # 1. Punctuacion fuerte: corte inmediato (oracion termina).
    m = _HARD_PUNCT_RE.search(buf)
    if m:
        return m.end()

    word_count = len(buf.split())

    # 2. Punctuacion suave + min de palabras: corte natural en coma/punto y coma.
    m_soft = _SOFT_PUNCT_RE.search(buf)
    if m_soft:
        words_before = len(buf[:m_soft.end()].split())
        if words_before >= _MIN_WORDS_AFTER_SOFT:
            return m_soft.end()

    # 3. Demasiadas palabras acumuladas sin puntuacion: corte forzado en ultimo espacio.
    if word_count >= _MAX_WORDS_PER_CHUNK:
        words = buf.split()
        cut_text = " ".join(words[:_MAX_WORDS_PER_CHUNK])
        # encontrar fin de esa cadena en buf original (puede tener whitespace extra)
        idx = 0
        for w in words[:_MAX_WORDS_PER_CHUNK]:
            idx = buf.index(w, idx) + len(w)
        return idx

    return None


def stream_to_sentences(deltas: Iterator[str], streamer: TTSStreamer) -> None:
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


def stop_path() -> int:
    pid = read_recorder_pid()
    if pid is None:
        log("stop called but no live recorder")
        return 1
    log(f"signaling recorder pid={pid}")
    signal_stop(pid)
    return 0


def abort_path() -> int:
    pid = read_owner_pid()
    if pid is None:
        log("abort called but no owner")
        return 1
    log(f"signaling abort to owner pid={pid}")
    signal_cancel(pid)
    orb_state("cancel")
    return 0


def start_path() -> int:
    ensure_orb()
    ensure_monitor_open()
    prewarm_whisper()  # modelo carga en paralelo mientras el usuario graba
    LOCK_FILE.write_text(str(os.getpid()))
    signal.signal(signal.SIGUSR2, cancel_handler)

    try:
        try:
            duration = record_until_signaled()
        finally:
            PID_FILE.unlink(missing_ok=True)

        if _cancel.is_set():
            log("cancel after rec")
            orb_state("cancel")
            return 0

        if duration < MIN_DURATION_S:
            orb_state("error")
            return 0

        orb_state("transcribe")
        text = transcribe()

        if _cancel.is_set():
            log("cancel after transcribe")
            orb_state("cancel")
            return 0

        if not text:
            orb_state("error")
            return 0

        if is_reset_command(text):
            new_sid = reset_session()
            log(f"reset by voice keyword -> {new_sid}")
            orb_state("nueva")
            return 0

        # Captura screenshot SOLO si el prompt referencia algo visual.
        # Esto evita capturas innecesarias en calls normales (la mayoria).
        attach_screenshot: Path | None = None
        if is_visual_command(text):
            log("visual keyword detected, capturing screenshot")
            attach_screenshot = take_screenshot()
            if attach_screenshot is not None:
                orb_state("screen")
            else:
                orb_state("think")
        else:
            orb_state("think")

        streamer = TTSStreamer()
        set_current_streamer(streamer)

        def on_first_token() -> None:
            orb_state("speak")

        try:
            stream_to_sentences(
                ask_claude_stream(
                    text,
                    on_first_token=on_first_token,
                    screenshot_path=attach_screenshot,
                ),
                streamer,
            )
        finally:
            streamer.finish()
            streamer.wait(timeout=120)
            set_current_streamer(None)

        if _cancel.is_set():
            log("cancel during streaming")
            orb_state("cancel")
            return 0

        orb_state("idle")
        return 0
    finally:
        LOCK_FILE.unlink(missing_ok=True)


def main() -> int:
    PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    load_word_aliases()

    recorder_pid = read_recorder_pid()
    if recorder_pid is not None:
        return stop_path()

    owner_pid = read_owner_pid()
    if owner_pid is not None:
        log(f"busy: owner pid={owner_pid} -> abort")
        return abort_path()

    return start_path()


if __name__ == "__main__":
    sys.exit(main())
