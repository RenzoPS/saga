"""Configuración central: paths, flags, voces, regexes. Sin lógica."""

import os
import re
from pathlib import Path

HOME = Path.home()
PROJECT_DIR = HOME / ".local/share/voice-claude"
PID_FILE = Path("/tmp/voice-claude.pid")
LOCK_FILE = Path("/tmp/voice-claude.lock")
ABORT_FILE = Path("/tmp/voice-claude.abort")  # pid del último owner abortado (detección de zombie)
AUDIO_FILE = Path("/tmp/voice-claude.wav")
LOG_FILE = PROJECT_DIR / "voice_claude.log"

EDGE_VOICE = "es-AR-ElenaNeural"  # Microsoft Edge TTS, voz argentina femenina
EDGE_RATE = "+5%"  # ligeramente mas rapida
EDGE_PITCH = "+0Hz"

WHISPER_SIZE = os.environ.get("VOICE_WHISPER_SIZE", "small")  # small: preciso (para voz, entender bien > 2s). base = más rápido/menos preciso
WHISPER_BEAM = int(os.environ.get("VOICE_WHISPER_BEAM", "5"))  # beam5 con base: costo ~nulo (medido) + búsqueda robusta. beam1 dispara loops
# Daemon STT: mantiene el modelo caliente en RAM entre invocaciones (mata los ~3s
# de recarga por Win+Z). transcribe() es cliente; si el daemon esta caido cae a inline.
WHISPER_SOCK = Path("/tmp/voice-claude-whisper.sock")
WHISPER_DAEMON = PROJECT_DIR / "whisper_daemon.py"
WHISPER_IDLE_S = 1800  # daemon se autoapaga tras 30 min sin uso
# Params de decodificación de Whisper, UNA sola fuente (los usan el daemon y el
# fallback inline -> antes estaban duplicados y se desincronizaban). beam_size y
# language van aparte. temperature como lista = fallback; no_repeat_ngram mata loops.
WHISPER_DECODE = dict(
    vad_filter=True,
    condition_on_previous_text=False,
    temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
    compression_ratio_threshold=2.4,
    log_prob_threshold=-1.0,
    no_speech_threshold=0.6,
    no_repeat_ngram_size=3,
)

CLAUDE_MODEL = os.environ.get("VOICE_CLAUDE_MODEL", "sonnet")  # sonnet: respuestas mucho mejores (haiku flojo). Más lento/caro. env -> "haiku" para volver
# Saltar permisos de Claude (modo dios). Default ON para no romper el flujo actual;
# exportá VOICE_CLAUDE_SAFE=1 para correr en modo seguro (Claude pide permisos).
CLAUDE_SKIP_PERMISSIONS = os.environ.get("VOICE_CLAUDE_SAFE") != "1"

# Arranque liviano del CLI -> primer token MUCHO mas rapido (de ~57s a ~7s).
# Mata lo que el voice-assistant no necesita y arrancaba en CADA Win+Z:
#  - MCP servers pesados (playwright lanzaba un Chromium, npx bajaba paquetes, Google MCPs timeouteaban)
#  - resto de plugins/hooks/skills (caveman, superpowers, context-mode) via --setting-sources ''
# Mantiene claude-mem COMPLETO (recall + captura + hooks + su MCP) via --plugin-dir.
_CLAUDE_MEM_BASE = HOME / ".claude/plugins/cache/thedotmack/claude-mem"


def _detect_claude_mem_dir() -> "str | None":
    """Autodetecta el dir de la version MAS NUEVA de claude-mem (evita hardcodear
    el numero de version, que se rompe en cada update). Override con env."""
    override = os.environ.get("VOICE_CLAUDE_MEM_DIR")
    if override:
        return override
    if not _CLAUDE_MEM_BASE.is_dir():
        return None
    versions = [p for p in _CLAUDE_MEM_BASE.iterdir() if p.is_dir() and p.name[:1].isdigit()]
    if not versions:
        return None

    def _semver(p: Path) -> tuple:
        return tuple(int(x) for x in re.findall(r"\d+", p.name)[:3])

    return str(sorted(versions, key=_semver)[-1])


CLAUDE_MEM_DIR = _detect_claude_mem_dir()
CLAUDE_FAST_FLAGS = ["--setting-sources", "", "--disable-slash-commands"]
if CLAUDE_MEM_DIR:
    CLAUDE_FAST_FLAGS = ["--plugin-dir", CLAUDE_MEM_DIR] + CLAUDE_FAST_FLAGS

# Daemon de Claude: proceso `claude` persistente (stream-json) que mantiene plugins
# + sesión calientes entre turnos -> mata el cold-start (~5s) de spawnear el CLI cada vez.
CLAUDE_SOCK = Path("/tmp/voice-claude-claude.sock")
CLAUDE_DAEMON = PROJECT_DIR / "claude_daemon.py"
CLAUDE_DAEMON_IDLE_S = 3600  # el proceso claude se autoapaga tras 1h sin turnos

# System prompt del asistente (constante -> se setea una vez al spawnear el daemon).
CLAUDE_SYSTEM_PROMPT = (
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
