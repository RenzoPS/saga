"""Configuración central: paths, flags, voces, regexes. Sin lógica."""

import os
import re
import json
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
WHISPER_BEAM = int(os.environ.get("VOICE_WHISPER_BEAM", "5"))  # beam5: búsqueda más amplia/robusta con small (preferencia del usuario). beam1 dispara loops
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

# Red de seguridad: hook PreToolUse que bloquea comandos Bash catastróficos antes
# de ejecutarse (god-mode + voz -> un mishear no puede borrar el disco). Los hooks
# corren aún con --dangerously-skip-permissions. Se inyecta vía --settings (aditivo,
# no reactiva las setting-sources). Ver vc/guard.py.
GUARD_SCRIPT = PROJECT_DIR / "vc" / "guard.py"
GUARD_SETTINGS = PROJECT_DIR / ".guard-settings.json"


def _ensure_guard_settings() -> "str | None":
    try:
        GUARD_SETTINGS.write_text(json.dumps({"hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [
                {"type": "command", "command": f"python3 {GUARD_SCRIPT}"}]}]}}))
        return str(GUARD_SETTINGS)
    except OSError:
        return None  # degradación: sin guard pero el asistente sigue andando


_GUARD = _ensure_guard_settings()
CLAUDE_FAST_FLAGS = ["--setting-sources", "", "--disable-slash-commands"]
if _GUARD:
    CLAUDE_FAST_FLAGS = ["--settings", _GUARD] + CLAUDE_FAST_FLAGS
# claude-mem en el daemon de voz: recall + captura por turno. PROBADO en vivo: el
# hook de recall (antes de responder) infla el TTFT de ~2s a 4-7s -> demasiado para
# voz. Default OFF (la velocidad gana). El transcript queda en voice_claude.log, así
# que lo importante se puede ingestar a demanda (sesión Claude -> Obsidian) sin pagar
# latencia por turno. VOICE_CLAUDE_MEM=1 lo reactiva. Respawnear el daemon al cambiar.
CLAUDE_MEM_ENABLED = os.environ.get("VOICE_CLAUDE_MEM", "0") == "1"
if CLAUDE_MEM_DIR and CLAUDE_MEM_ENABLED:
    CLAUDE_FAST_FLAGS = ["--plugin-dir", CLAUDE_MEM_DIR] + CLAUDE_FAST_FLAGS


def build_claude_base_args(session_id: str, flag: str) -> list:
    """Args base de `claude`, fuente ÚNICA para el daemon y el one-shot (antes
    estaban duplicados y driftaban). El caller agrega el modo:
      - daemon / one-shot con imagen: + ['-p', '--input-format', 'stream-json'] (prompt por stdin)
      - one-shot de texto: + ['-p', prompt]"""
    args = [
        "claude", "--model", CLAUDE_MODEL,
        "--output-format", "stream-json", "--verbose", "--include-partial-messages",
        "--append-system-prompt", CLAUDE_SYSTEM_PROMPT, flag, session_id,
    ]
    args += CLAUDE_FAST_FLAGS
    if CLAUDE_SKIP_PERMISSIONS:
        args.append("--dangerously-skip-permissions")
    return args

# Daemon de Claude: proceso `claude` persistente (stream-json) que mantiene plugins
# + sesión calientes entre turnos -> mata el cold-start (~5s) de spawnear el CLI cada vez.
CLAUDE_SOCK = Path("/tmp/voice-claude-claude.sock")
CLAUDE_DAEMON = PROJECT_DIR / "claude_daemon.py"
CLAUDE_DAEMON_IDLE_S = 3600  # el proceso claude se autoapaga tras 1h sin turnos
CLAUDE_DAEMON_TURN_TIMEOUT_S = 180  # techo por turno: si claude se cuelga, matar+respawn (no trabar el daemon)

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

# Auto-stop por silencio (VAD Silero) también en el flujo Win+Z, no solo en modo wake.
# Default ON: apretás Win+Z, hablás, y corta solo al callar (no hace falta 2do Win+Z
# para cortar). El 2do Win+Z para cortar a mano sigue andando igual. VOICE_AUTOSTOP=0
# vuelve al modo clásico "Win+Z arranca / Win+Z corta".
AUTOSTOP_ON_MANUAL = os.environ.get("VOICE_AUTOSTOP", "1") != "0"

# Modo LiveKit. Cuando está ON, el runtime de audio (captura, streaming, chunks, VAD,
# turn detection, barge-in) lo maneja livekit-agents (lk/agent.py console) EN VEZ de
# nuestro whisper_daemon + flujo Win+Z. Claude sigue siendo el cerebro y el orbe +
# edge-tts se reusan. Default ON -> `vc-ctl start` levanta el agente LiveKit. Para
# volver al modo clásico (Win+Z por-turno): VOICE_LIVEKIT=0. Ver lk/README.md.
LIVEKIT_ENABLED = os.environ.get("VOICE_LIVEKIT", "1") != "0"
LK_AGENT = PROJECT_DIR / "lk" / "agent.py"
LK_LOG = PROJECT_DIR / "livekit_agent.log"
# Socket de control: Win+Z (vc/app.py) le manda "toggle"/"on"/"off" al agente para
# prender/apagar el mic (push-to-talk). Lo crea y escucha el proceso del agente.
LK_CTL_SOCK = Path("/tmp/voice-claude-lk-ctl.sock")

# Secretos del proyecto (API keys). Archivo gitignored, cargado por el agente con
# python-dotenv. NO es config seteable: el STT/TTS los decide el código (Deepgram por
# default; si no hay key, cae solo a whisper/edge). Acá solo vive el secreto.
ENV_FILE = PROJECT_DIR / ".env.local"

MONITOR_CLASS = "voice-claude-monitor"
MONITOR_WORKSPACE = 10

SCREENSHOT_PATH = Path("/tmp/voice-claude-screenshot.png")

# Adjuntos pegados desde la pestaña del orbe (texto/imagen). El navegador los manda por
# POST a orb_server, que los escribe acá; el agente (lk/claude_llm) los lee en el turno y
# los borra (consume-once, mismo patrón dead-drop que SCREENSHOT_PATH). /tmp es tmpfs (RAM).
ATTACH_TEXT_PATH = Path("/tmp/voice-claude-attach.txt")
ATTACH_IMG_PATH = Path("/tmp/voice-claude-attach.png")

# Orbe visual: server SSE persistente en localhost, la pagina (orb/orb.html) se
# sincroniza en vivo con la fase actual.
ORB_DIR = PROJECT_DIR / "orb"
ORB_PORT = int(os.environ.get("ORB_PORT", "8777"))
ORB_URL = f"http://127.0.0.1:{ORB_PORT}/"
ORB_SERVER = ORB_DIR / "orb_server.py"

# Diccionario de palabras-problema (JSON editable). Se aplica en clean_for_tts.
WORD_ALIASES_PATH = PROJECT_DIR / "word_aliases.json"

SESSION_FILE = PROJECT_DIR / "session.json"

# Wake word ON/OFF. Default OFF: el trigger es Win+Z (sin escucha continua -> 0
# falsos positivos, 0 contención de mic, un daemon menos). El wake_daemon y TODO su
# código quedan intactos; VOICE_WAKE_ENABLED=1 reactiva la escucha de "claude".
# Lo lee vcctl al levantar para decidir si lanza el wake_daemon.
WAKE_ENABLED = os.environ.get("VOICE_WAKE_ENABLED", "0") == "1"

# Wake word: daemon Vosk que escucha el mic en continuo y dispara el flujo al oir
# "claude" (o variantes que el STT chico confunde). Local, sin cuenta, sin training.
WAKE_MODEL_DIR = PROJECT_DIR / "models" / "vosk-model-small-es-0.42"
WAKE_BEEP_FILE = Path("/tmp/voice-claude-beep.wav")  # se genera una vez al arrancar el daemon
# Vosk con GRAMMAR restringida: el recognizer DEBE mapear el audio a una de estas
# frases o a "[unk]" (que absorbe todo lo demás y queda mudo). Medido en vivo: el
# recognizer libre escupe basura ('law','icloud','grau') para "claude", pero con
# grammar clava "claude"/"hey claude" y queda mudo en charla normal (casi 0 falsos +).
# "claude" no está en el léxico ES pero Vosk lo acepta en grammar igual; "claudio/
# claudia" sí están y atrapan las veces que el AM lo desvía a esos nombres.
# "claudio"/"claudia" quedan como SEÑUELOS: están en la grammar para darle a Vosk
# dónde rutear los casi-match (audio del sistema, ruido, voz lejana) en vez de
# forzarlos a "claude". NO disparan -> ver WAKE_TRIGGER_PHRASES.
WAKE_GRAMMAR = ("claude", "hey claude", "claudio", "claudia", "[unk]")
# Dispara SOLO si el texto FINAL completo es EXACTAMENTE una de estas frases. Match
# de frase entera, no substring: 'claudia'/'claudio'/'claude algo'/'la nube claude' NO
# levantan. 'claudia'/'claudio' siguen en WAKE_GRAMMAR como señuelos: absorben el ruido
# parecido (lo rutean ahí en vez de a 'claude'), pero al no estar acá, no disparan.
WAKE_TRIGGER_PHRASES = ("claude", "hey claude")
# Confianza mínima (la palabra más floja del match, 0..1) para aceptar el wake. Vosk solo
# da conf en resultados FINALES. Subir si vuelven los falsos +, bajar si cuesta levantar.
# Arranca permisivo; tunear con las líneas 'final candidato' del log.
WAKE_MIN_CONF = 0.7
WAKE_COOLDOWN_S = 2.0  # tras un disparo, ignorar nuevos hasta que pase esto (anti doble-beep)
# Modo conversación: tras el wake, sigue grabando turnos sin re-decir "claude" hasta
# que digas una despedida. Match: el texto del turno es CORTO y contiene una frase.
GOODBYE_KEYWORDS = (
    "gracias", "muchas gracias", "muchisimas gracias", "muchísimas gracias",
    "listo", "terminamos", "estamos", "todo ready", "todo listo", "ya esta",
    "ya está", "eso es todo", "eso seria todo", "eso sería todo", "nada mas",
    "nada más", "chau", "chao", "perfecto gracias", "dale gracias",
)
WAKE_MAX_IDLE_TURNS = 3  # silencios/vacíos seguidos -> cortar la conversación sola

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
