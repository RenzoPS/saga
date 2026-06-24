"""Configuración central: paths, flags, voces, regexes. Sin lógica."""

import os
import re
import json
from pathlib import Path

HOME = Path.home()
PROJECT_DIR = HOME / ".local/share/saga"
LOG_FILE = PROJECT_DIR / "saga.log"

EDGE_VOICE = "es-AR-ElenaNeural"  # Microsoft Edge TTS, voz argentina femenina
EDGE_RATE = "+5%"  # ligeramente mas rapida
EDGE_PITCH = "+0Hz"

WHISPER_SIZE = os.environ.get("VOICE_WHISPER_SIZE", "small")  # small: preciso (para voz, entender bien > 2s). base = más rápido/menos preciso
WHISPER_BEAM = int(os.environ.get("VOICE_WHISPER_BEAM", "5"))  # beam5: búsqueda más amplia/robusta con small (preferencia del usuario). beam1 dispara loops
# Params de decodificación de Whisper (faster-whisper en el agente cuando NO hay key Deepgram).
# temperature como lista = fallback; no_repeat_ngram mata loops.
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
# voz. Default OFF (la velocidad gana). El transcript queda en saga.log, así
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
CLAUDE_SOCK = Path("/tmp/saga-claude.sock")
CLAUDE_DAEMON = PROJECT_DIR / "claude_daemon.py"
CLAUDE_DAEMON_IDLE_S = 3600  # el proceso claude se autoapaga tras 1h sin turnos
CLAUDE_DAEMON_TURN_TIMEOUT_S = 180  # techo por turno: si claude se cuelga, matar+respawn (no trabar el daemon)

# System prompt del asistente (constante -> se setea una vez al spawnear el daemon).
CLAUDE_SYSTEM_PROMPT = (
    "Te llamas Saga, el asistente de voz personal de Renzo. Si te preguntan tu nombre, sos Saga. "
    "\n\n"
    "Estas hablando, no escribiendo. Tu respuesta sale por parlante (TTS multilingue "
    "que pronuncia bien anglicismos, numeros, simbolos y siglas; no te preocupes por fonetizar). "
    "\n\n"
    "Reglas firmes:\n"
    "- Texto plano. Nada de markdown: sin asteriscos, sin backticks, sin listas con guiones o numeros, sin headers.\n"
    "- Espanol rioplatense: vos, dale, che, fijate.\n"
    "- Largo proporcional: pregunta corta = respuesta corta. Tono conversacional, directo, sin floreos.\n"
    "- Sos agentica: tenes tools (bash, leer/escribir archivos, etc.). Si te piden una ACCION que podes hacer "
    "en esta maquina (abrir una app, reproducir/pausar musica con playerctl o el comando que sea, decir la hora "
    "con date, mirar algo del sistema), HACELA con la tool y despues confirma corto lo que hiciste. No digas "
    "'no puedo' si tenes como hacerlo. Solo si REALMENTE no hay forma, una sola frase corta sin disculpas ni listas.\n"
    "\n"
    "Estilo:\n"
    "Hablas como si le contaras algo a un amigo en un cafe. Nada de 'primero, segundo, tercero', "
    "'aspectos clave', 'puntos importantes', 'cabe destacar'. Frases fluidas, conectadas. "
    "Conectores naturales: 'asi que', 'entonces', 'igual', 'mira', 'fijate'. "
    "Si explicas algo tecnico, lo contas como historia, no como manual."
)

SAMPLE_RATE = 16000   # lo usa el wake_daemon (Vosk, dormido)
CLAUDE_TIMEOUT_S = 180

LK_AGENT = PROJECT_DIR / "lk" / "agent.py"
LK_LOG = PROJECT_DIR / "livekit_agent.log"
# Socket de control: Win+Z (vc/app.py) le manda "press" al agente para prender/apagar el mic
# (push-to-talk). Lo crea y escucha el proceso del agente.
LK_CTL_SOCK = Path("/tmp/saga-lk-ctl.sock")

# Secretos del proyecto (API keys). Archivo gitignored, cargado por el agente con
# python-dotenv. NO es config seteable: el STT/TTS los decide el código (Deepgram por
# default; si no hay key, cae solo a whisper/edge). Acá solo vive el secreto.
ENV_FILE = PROJECT_DIR / ".env.local"

# Cargamos .env.local acá (no solo en el agente) para que CUALQUIER importador de config
# —incluido orb_server, que mintea el JWT en /token— vea LIVEKIT_API_KEY/SECRET y demás.
# load_dotenv es idempotente y no pisa env ya seteadas; si falta dotenv, se degrada en silencio.
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(ENV_FILE)
except Exception:
    pass

# Transporte room (Ciclo 4). El worker (lk/agent.py) y el token endpoint (orb_server) leen
# de acá. URL/room tienen default local; las keys viven SOLO en .env.local (secreto). El
# server bindea a loopback (livekit.yaml) -> nada sale de la máquina.
LIVEKIT_URL = os.environ.get("LIVEKIT_URL", "ws://127.0.0.1:7880")
LIVEKIT_API_KEY = os.environ.get("LIVEKIT_API_KEY", "")
LIVEKIT_API_SECRET = os.environ.get("LIVEKIT_API_SECRET", "")
LIVEKIT_ROOM = os.environ.get("LIVEKIT_ROOM", "saga")
# (U8) El worker usa DISPATCH AUTOMÁTICO nativo: se registra sin agent_name y el server lo despacha
# solo cuando el browser crea el room "saga". Ya NO hay un LIVEKIT_AGENT_NAME ni dispatch por API.

# Server room (Ciclo 4, U6): binario NATIVO + su config. saga-ctl lo levanta/baja en modo room.
# (Se usa el binario, NO Docker: el NAT de Docker rompía el WebRTC local — ver aidlc-docs.)
LIVEKIT_SERVER_BIN = HOME / ".local/bin/livekit-server"
LIVEKIT_CONFIG = PROJECT_DIR / "livekit.yaml"
LK_SERVER_LOG = PROJECT_DIR / "livekit_server.log"
LIVEKIT_SIGNAL_PORT = 7880   # signaling (loopback) — readiness del server

MONITOR_CLASS = "saga-monitor"
MONITOR_WORKSPACE = 10

SCREENSHOT_PATH = Path("/tmp/saga-screenshot.png")

# Adjunto IMAGEN pegado desde la pestaña del orbe. El navegador la manda por POST a orb_server,
# que la escribe acá; el agente (lk/claude_llm) la lee en el turno como screenshot_path y la
# borra (consume-once, mismo patrón dead-drop que SCREENSHOT_PATH). /tmp es tmpfs (RAM).
# (El TEXTO ya NO va por archivo: se stagea en memoria del agente vía el socket de control.)
ATTACH_IMG_PATH = Path("/tmp/saga-attach.png")

# Orbe visual: server SSE persistente en localhost, la pagina (orb/orb.html) se
# sincroniza en vivo con la fase actual.
ORB_DIR = PROJECT_DIR / "orb"
ORB_PORT = int(os.environ.get("ORB_PORT", "8777"))
ORB_URL = f"http://127.0.0.1:{ORB_PORT}/"
ORB_SERVER = ORB_DIR / "orb_server.py"

SESSION_FILE = PROJECT_DIR / "session.json"

# Wake word del agente LiveKit: ON/OFF con SAGA_WAKE_ENABLED (lo leen lk/agent.py + orb_server).
# Default OFF: el trigger es Win+Z. Modelo "hey saga" (U4) sobre el track del browser.

# Wake word clásico (Vosk, DORMIDO/fuera de scope): daemon que escuchaba el mic y disparaba el
# "saga" (o variantes que el STT chico confunde). Local, sin cuenta, sin training.
# Ventaja sobre "claude": "saga" SI esta en el lexico ES -> Vosk la reconoce nativo.
WAKE_MODEL_DIR = PROJECT_DIR / "models" / "vosk-model-small-es-0.42"
WAKE_BEEP_FILE = Path("/tmp/saga-beep.wav")  # se genera una vez al arrancar el daemon
# Vosk con GRAMMAR restringida: el recognizer DEBE mapear el audio a una de estas
# frases o a "[unk]" (que absorbe todo lo demás y queda mudo). Con grammar clava
# "saga"/"hey saga" y queda mudo en charla normal (casi 0 falsos +).
# "zaga"/"saca" quedan como SEÑUELOS: están en la grammar para darle a Vosk
# dónde rutear los casi-match (audio del sistema, ruido, voz lejana) en vez de
# forzarlos a "saga". NO disparan -> ver WAKE_TRIGGER_PHRASES.
WAKE_GRAMMAR = ("saga", "hey saga", "zaga", "saca", "[unk]")
# Dispara SOLO si el texto FINAL completo es EXACTAMENTE una de estas frases. Match
# de frase entera, no substring: 'zaga'/'saca'/'saga algo'/'la saga esa' NO
# levantan. 'zaga'/'saca' siguen en WAKE_GRAMMAR como señuelos: absorben el ruido
# parecido (lo rutean ahí en vez de a 'saga'), pero al no estar acá, no disparan.
WAKE_TRIGGER_PHRASES = ("saga", "hey saga")
# Confianza mínima (la palabra más floja del match, 0..1) para aceptar el wake. Vosk solo
# da conf en resultados FINALES. Subir si vuelven los falsos +, bajar si cuesta levantar.
# Arranca permisivo; tunear con las líneas 'final candidato' del log.
WAKE_MIN_CONF = 0.7
WAKE_COOLDOWN_S = 2.0  # tras un disparo, ignorar nuevos hasta que pase esto (anti doble-beep)

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
