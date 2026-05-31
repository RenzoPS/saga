"""Configuración central: paths, flags, voces, regexes. Sin lógica."""

import os
import re
from pathlib import Path

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

# Orbe visual: server SSE persistente en localhost, la pagina (orb/orb.html) se
# sincroniza en vivo con la fase actual.
ORB_DIR = PROJECT_DIR / "orb"
ORB_PORT = int(os.environ.get("ORB_PORT", "8777"))
ORB_URL = f"http://127.0.0.1:{ORB_PORT}/"
ORB_SERVER = ORB_DIR / "orb_server.py"

# Diccionario de palabras-problema (JSON editable). Se aplica en clean_for_tts.
WORD_ALIASES_PATH = PROJECT_DIR / "word_aliases.json"

SESSION_FILE = PROJECT_DIR / "session.json"

# Regex que matchea CUALQUIER mencion visual como palabra suelta.
# Usa word boundaries para evitar falsos positivos (ej "admira" no matchea "mira").
VISUAL_RE = re.compile(
    r"\b("
    r"mira|mirá|mirar|miralo|míralo|miremos|"
    r"fijate|fíjate|fijensé|"
    r"ves|podes ver|podés ver|puedes ver|"
    r"estoy viendo|estoy mirando|"
    r"mostrarte|mostrar|muestro|mostrame|"
    r"pantalla|"
    r"aca en|acá en|aqui en|aquí en|"
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
