"""Generadores de dominio para los property-based tests (PBT-07).

Regla PBT-07: NADA de primitivos crudos para tipos de dominio. `st.text()` jamás
produciría un comando shell plausible ni un estado válido del orbe. Cada generador
compone datos con la estructura real del dominio, incluyendo los ejes que exponen bugs.

Módulo único y reutilizable (PBT-07): no duplicar generadores entre archivos de test.
"""

import json

from hypothesis import strategies as st

# --- E1: Estado del orbe (fuente: orb/orb_server.py VALID_STATES) ---
VALID_ORB_STATES = [
    "idle", "rec", "transcribe", "screen",
    "think", "speak", "nueva", "error", "cancel", "attach",
]


@st.composite
def orb_states(draw):
    """Estados del orbe: válidos, válidos-con-ruido, inválidos plausibles, arbitrarios, None, vacío.
    Cubre todo lo que puede llegar a normalize_state por SSE/POST."""
    kind = draw(st.integers(min_value=0, max_value=5))
    if kind == 0:
        return draw(st.sampled_from(VALID_ORB_STATES))
    if kind == 1:  # válido con ruido (mayúsculas, espacios alrededor)
        base = draw(st.sampled_from(VALID_ORB_STATES))
        return draw(st.sampled_from([base.upper(), f"  {base}  ", base.capitalize()]))
    if kind == 2:  # inválido plausible
        return draw(st.sampled_from(["recording", "idle2", "thinking", "done", "ready"]))
    if kind == 3:
        return draw(st.text())
    if kind == 4:
        return None
    return ""


# --- E3: Contenido del archivo de blacklist (fuente: config._read_plugins_blacklist) ---
@st.composite
def blacklist_file_contents(draw):
    """Bytes que puede tener configs/plugins-blacklist.json. El parser NUNCA debe crashear (P5):
    JSON válido, tipos equivocados, sin la clave, raíz no-dict, JSON roto, binario, vacío."""
    kind = draw(st.integers(min_value=0, max_value=6))
    if kind == 0:  # JSON bien formado
        items = draw(st.lists(st.text(min_size=1, max_size=30), max_size=8))
        return json.dumps({"disabledPlugins": items}).encode()
    if kind == 1:  # disabledPlugins con tipo equivocado
        bad = draw(st.sampled_from([42, "una-string", None, {"x": 1}, [1, 2, 3]]))
        return json.dumps({"disabledPlugins": bad}).encode()
    if kind == 2:  # dict válido pero sin la clave
        return json.dumps({"otra": draw(st.text(max_size=20))}).encode()
    if kind == 3:  # raíz que no es dict
        return json.dumps(draw(st.one_of(st.lists(st.integers()), st.integers(), st.text()))).encode()
    if kind == 4:  # JSON sintácticamente roto
        return draw(st.sampled_from([b"{", b"{'x':}", b"not json at all", b'{"a": ,}']))
    if kind == 5:  # binario arbitrario
        return draw(st.binary(max_size=64))
    return b""  # vacío


# --- E6: Comandos shell (fuente: business-rules.md, listas de decisión) ---
# Plantillas catastróficas: (binario, [flags], operando). El generador varía el eje que expone bypasses.
_CATASTROPHIC = [
    ("rm", ["r", "f"], "/"),               # rm -rf / (flags juntas vs separadas = el bypass conocido)
    ("rm", ["r", "f"], "~/algo"),
    ("mkfs.ext4", [], "/dev/sdb"),
    ("shred", [], "/dev/sda"),
    ("wipefs", [], "/dev/sda"),
]

_BENIGN = [
    "ls -la", "cat archivo.py", "date", "git status", "git log --oneline",
    "npm install", "mkdir build", "rm archivo.txt", "sudo pacman -S wmctrl",
    "echo hola", "grep -rn foo .", "python script.py",
]


@st.composite
def catastrophic_commands(draw):
    """Comandos catastróficos con variaciones REALISTAS (P7). El eje clave: flags juntas vs separadas.
    Se ESPERA que este generador encuentre inputs que la denylist actual NO bloquea (bypasses)."""
    binario, flags, operando = draw(st.sampled_from(_CATASTROPHIC))
    parts = []
    if draw(st.booleans()):
        parts.append("sudo")
    parts.append(binario)
    if flags:
        style = draw(st.integers(min_value=0, max_value=2))
        if style == 0:                       # juntas: -rf
            parts.append("-" + "".join(flags))
        elif style == 1:                     # separadas: -r -f  <-- expone el bypass
            parts.extend("-" + f for f in flags)
        else:                                # forma larga: --recursive --force
            longmap = {"r": "--recursive", "f": "--force"}
            parts.extend(longmap.get(f, "-" + f) for f in flags)
    if operando:
        if draw(st.booleans()):
            operando = f'"{operando}"'       # quoting
        parts.append(operando)
    sep = draw(st.sampled_from([" ", "  ", " \t "]))  # espaciado variable
    return sep.join(parts)


@st.composite
def benign_commands(draw):
    """Comandos legítimos que el guard NO debe bloquear (P8). Un falso positivo = guard desactivado."""
    return draw(st.sampled_from(_BENIGN))


# --- E5: Payloads del socket de control (fuente: orb_server._forward_ctl) ---
# El body de un POST son bytes crudos -> el dominio real del payload es st.binary().
# Para el texto usamos st.characters(codec="utf-8") que excluye surrogates (\ud800..) no encodables.
_utf8_text = st.text(alphabet=st.characters(codec="utf-8"), max_size=128)


# --- E2: Header Host adversarial (fuente: orb_server._gate, U2/FR3.7) ---
# El bug clasico es el match por substring: `"127.0.0.1" in host` deja pasar 127.0.0.1.evil.com.
# El generador produce justo esos hosts que un check ingenuo aceptaria pero la allowlist exacta NO.
@st.composite
def adversarial_hosts(draw, port):
    """Hosts que NO deben pasar el check exacto, aunque contengan una substring loopback (P2)."""
    p = port
    templates = [
        f"127.0.0.1.evil.com:{p}",       # substring al principio
        f"evil.com:{p}",                 # nada que ver
        f"127.0.0.1:{p}.evil.com",       # substring con el puerto adentro
        f"localhost.evil.com:{p}",
        f"127.0.0.1:{p + 1}",            # loopback pero PUERTO equivocado
        f"127.0.0.1",                    # sin puerto
        f"[::1]:{p}.evil.com",
        f"0.0.0.0:{p}",
        f"127.0.0.1:{p} ",               # trailing space
        f"foo{p}bar",
    ]
    base = draw(st.sampled_from(templates))
    return base


@st.composite
def socket_payloads(draw):
    """Bytes que viajan por el socket de control como base64. Incluye texto con \\n embebidos:
    el caso que motiva P4 (el framing por readline() no se puede romper)."""
    kind = draw(st.integers(min_value=0, max_value=4))
    if kind == 0:
        return draw(st.binary(max_size=256))
    if kind == 1:
        return draw(_utf8_text).encode("utf-8")
    if kind == 2:  # texto CON saltos de línea (el caso peligroso)
        return draw(_utf8_text).encode("utf-8") + b"\ninyectado"
    if kind == 3:
        return b""
    return draw(st.binary(min_size=200, max_size=1000))  # payloads largos
