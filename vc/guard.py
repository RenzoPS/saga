#!/usr/bin/env python3
"""PreToolUse hook: bloquea comandos Bash CATASTRÓFICOS/irreversibles y MALAS PRÁCTICAS
de git antes de ejecutarlos. saga + voz = un mishear no puede borrar el disco ni reventar
el historial. Permite TODO lo demás (sudo install, builds, git normal, rm de un archivo).

Protocolo Claude Code PreToolUse: lee JSON por stdin con {tool_name, tool_input}.
Para bloquear: stdout JSON con permissionDecision=deny (exit 0).

FAIL-CLOSED (Ciclo 9 / U3, FR2.2, SECURITY-15). Antes esto era fail-OPEN "a propósito"
(no brickear el agente por un hiccup del hook). Se invirtió: la ruta del error es JUSTO la
que un atacante fuerza, y un control que se cae solo ante un input raro no es un control.
Si el guard no puede EVALUAR el comando, DENIEGA y lo dice.

Dos motores, y el veredicto es la UNIÓN de ambos (nunca la intersección):
  1. DENY (regex heredado) — lo que no se expresa como programa+flags: pipes a shell,
     redirecciones a /dev/sdX, fork bombs, sobrescritura de dotfiles.
  2. Reglas ESTRUCTURALES sobre el comando parseado (shlex) — el veredicto no puede depender
     de CÓMO se escribió el comando: `rm -rf` == `rm -r -f` == `rm --recursive --force`.
     El regex solo se evadía por ahí (Hypothesis lo demostró en U1: `rm -r -f` pasaba).

Que sea la UNIÓN es lo que garantiza la propiedad U3-P6 (oracle): el guard nuevo bloquea
TODO lo que bloqueaba el viejo. El rewrite no puede ABRIR un agujero que estaba tapado.
"""

import sys
import json
import re
import shlex
import os

# --- Motor 1: denylist heredada (regex sobre la línea cruda) ---------------------------------
# Se CONSERVA tal cual (es el oracle de no-regresión). Cubre lo que no tiene forma de
# "programa + flags": pipes, redirecciones, fork bombs.
DENY = [
    (r"\brm\s+-[a-z]*r[a-z]*f", "rm -rf (borrado recursivo forzado)"),
    (r"\brm\s+-[a-z]*f[a-z]*r", "rm -fr (borrado recursivo forzado)"),
    (r"\bdd\b[^|]*\bof=/dev/", "dd escribiendo a disco"),
    (r"\bmkfs\b", "formatear filesystem (mkfs)"),
    (r">\s*/dev/(sd|nvme|vd|mmcblk|disk)", "sobrescribir un disco"),
    (r":\s*\(\s*\)\s*\{.*:\s*\|\s*:.*&.*\}", "fork bomb"),
    (r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(ba|z|d)?sh\b", "pipe a shell (curl|sh)"),
    (r"\bgit\s+reset\s+--hard\b", "git reset --hard"),
    (r"\bgit\s+push\b[^&;|]*(--force\b|\s-f\b)", "git push --force"),
    (r"\bgit\s+clean\s+-[a-z]*f", "git clean -f"),
    (r">>?\s*~?/?\.?(zshrc|bashrc|bash_profile|profile|gitconfig)\b", "sobrescribir dotfile de shell"),
    (r"\b(shred|wipefs)\b", "shred/wipefs (destrucción de datos)"),
    (r"\bchmod\s+-R\b[^&;|]*\s/\s*$", "chmod -R sobre /"),
    (r"\bchown\s+-R\b[^&;|]*\s/\s*$", "chown -R sobre /"),
    (r"\btruncate\b[^&;|]*-s\s*0", "truncate -s 0 (vaciar archivo)"),
]

# --- Motor 2: reglas estructurales -----------------------------------------------------------

# Separadores de shell: cada subcomando se evalúa POR SEPARADO.
# `echo hola && rm -r -f /` es catastrófico aunque empiece con un echo inocente.
SEPARATORS = {";", "&&", "||", "|", "&", "\n"}

# Wrappers que NO son el comando real: hay que mirar lo que viene después.
# `sudo rm -r -f /` tiene program=sudo, pero el peligro es el rm.
WRAPPERS = {"sudo", "doas", "env", "nohup", "nice", "ionice", "time",
            "command", "builtin", "exec", "stdbuf", "setsid", "xargs"}

# Flags largas -> su equivalente corta. Así `--recursive --force` == `-rf` == `-r -f`.
LONG_TO_SHORT = {
    "--recursive": "r",
    "--force": "f",
}


class SubCommand:
    """Un comando ya parseado. `flags` está NORMALIZADO: -rf, -r -f, -fr y
    --recursive --force producen todos el mismo set {'r', 'f'}."""

    def __init__(self, program: str, flags: set, args: list, raw: str):
        self.program = program
        self.flags = flags
        self.args = args
        self.raw = raw


def _tokenize(line: str) -> list:
    """Tokeniza respetando comillas y separando la puntuación de shell.
    punctuation_chars=True hace que `a&&rm` se parta en ['a', '&&', 'rm'] (sin él,
    quedaría como un solo token y el separador se escondería)."""
    lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    return list(lexer)


def _normalize_flags(tokens: list) -> tuple:
    """Separa flags de argumentos posicionales. Expande las cortas agrupadas
    (-rf -> {'r','f'}) y traduce las largas conocidas (--force -> 'f').
    Preserva el CASE: `-R` (recursivo de chmod/rm) no es lo mismo que `-r`."""
    flags, args = set(), []
    for t in tokens:
        if t.startswith("--"):
            name = t.split("=", 1)[0]
            flags.add(LONG_TO_SHORT.get(name, name))
        elif t.startswith("-") and len(t) > 1:
            flags.update(t[1:])          # -rf -> {'r','f'}
        else:
            args.append(t)
    return flags, args


def _subcommands(cmd: str) -> list:
    """Parte la línea por separadores de shell y parsea cada trozo.
    Salta los wrappers (sudo/env/nohup...) para llegar al comando real."""
    subs: list = []
    current: list = []
    for tok in _tokenize(cmd):
        if tok in SEPARATORS:
            if current:
                subs.append(current)
            current = []
        else:
            current.append(tok)
    if current:
        subs.append(current)

    parsed = []
    for tokens in subs:
        while tokens and (tokens[0] in WRAPPERS or "=" in tokens[0] or tokens[0].startswith("-")):
            tokens = tokens[1:]          # sudo -u root rm ... -> rm ...
        if not tokens:
            continue
        program = os.path.basename(tokens[0])   # /usr/bin/rm -> rm
        flags, args = _normalize_flags(tokens[1:])
        parsed.append(SubCommand(program, flags, args, " ".join(tokens)))
    return parsed


def _structural_verdict(sc: SubCommand) -> "str | None":
    """Reglas sobre la ESTRUCTURA del comando. Es lo que cierra los bypasses que el
    regex dejaba pasar (`rm -r -f`, `rm --recursive --force`, `sudo rm -R -f`)."""
    prog, flags, args = sc.program, sc.flags, sc.args

    # --- Catastrófico / irreversible de sistema ---
    if prog == "rm" and (flags & {"r", "R"}) and "f" in flags:
        return "rm -rf (borrado recursivo forzado)"
    if prog.startswith("mkfs"):
        return "formatear filesystem (mkfs)"
    if prog == "dd" and any(a.startswith("of=/dev/") for a in args):
        return "dd escribiendo a disco"
    if prog in ("shred", "wipefs"):
        return "shred/wipefs (destrucción de datos)"
    if prog in ("chmod", "chown") and "R" in flags and "/" in args:
        return f"{prog} -R sobre /"
    if prog == "truncate" and ("s" in flags or "--size" in flags) and "0" in args:
        return "truncate -s 0 (vaciar archivo)"

    # --- MALAS PRÁCTICAS DE GIT (decisión explícita del usuario, Ciclo 9 / U3) ---
    # Bloqueo DURO: no pasan por confirmación hablada. Se hacen a mano, en una terminal.
    if prog == "git" and args:
        sub = args[0]
        if sub == "reset" and "--hard" in flags:
            return "git reset --hard"
        if sub == "push" and (flags & {"f", "--force", "--force-with-lease"}):
            return "git push --force"
        if sub == "clean" and "f" in flags:
            return "git clean -f"
    return None


def denied(cmd: str) -> "str | None":
    """Devuelve la etiqueta del patrón bloqueado si el comando es catastrófico o una mala
    práctica de git; None si puede pasar. Función pura -> testeable sin stdin.

    El veredicto es la UNIÓN de los dos motores (regex heredado + reglas estructurales):
    todo lo que bloqueaba el guard viejo lo sigue bloqueando el nuevo (propiedad U3-P6).
    """
    if not isinstance(cmd, str):
        return "input no evaluable (fail-closed)"     # ni intentar: no es un comando

    for pat, label in DENY:                            # motor 1: el de siempre
        if re.search(pat, cmd, re.IGNORECASE):
            return label

    try:                                               # motor 2: el que cierra los bypasses
        subs = _subcommands(cmd)
    except ValueError:
        # shlex no pudo parsear (comillas sin cerrar, sintaxis rota). NO se asume benigno:
        # el regex ya dijo que no, pero acá no podemos EVALUAR -> fail-closed.
        return "comando no parseable (fail-closed)"

    for sc in subs:
        veredicto = _structural_verdict(sc)
        if veredicto:
            return veredicto
    return None


def _deny(reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}))


def main() -> int:
    """Fail-closed: ante CUALQUIER anomalía, denegar. La única salida 'allow' silenciosa es
    para tools que no son Bash (fuera de la jurisdicción del guard)."""
    try:
        data = json.load(sys.stdin)
    except Exception:
        print("guard: input no parseable -> DENY (fail-closed)", file=sys.stderr)
        _deny("El guard de seguridad no pudo evaluar el comando (input no parseable). Denegado por precaución.")
        return 0

    try:
        if not isinstance(data, dict):
            print("guard: payload no es un objeto -> DENY", file=sys.stderr)
            _deny("El guard de seguridad no pudo evaluar el comando. Denegado por precaución.")
            return 0

        tool = data.get("tool_name")
        if not isinstance(tool, str):
            # No sabemos ni qué tool es -> no podemos evaluar -> fail-closed (BR-U3-2).
            print("guard: tool_name inválido -> DENY", file=sys.stderr)
            _deny("El guard de seguridad no pudo evaluar la herramienta. Denegado por precaución.")
            return 0
        if tool != "Bash":
            # No es Bash: fuera de jurisdicción. Las otras tools las cubre el permission-mode
            # nativo (auto), que sí ve TODO (incluidos los MCP).
            return 0

        tool_input = data.get("tool_input")
        if not isinstance(tool_input, dict):
            print("guard: tool_input inválido -> DENY", file=sys.stderr)
            _deny("El guard de seguridad no pudo evaluar el comando (tool_input inválido). Denegado por precaución.")
            return 0

        cmd = tool_input.get("command")
        if not isinstance(cmd, str):
            print("guard: command no es string -> DENY", file=sys.stderr)
            _deny("El guard de seguridad no pudo evaluar el comando (sin comando). Denegado por precaución.")
            return 0

        label = denied(cmd)
        if label:
            _deny(
                f"Bloqueado por seguridad de voz: {label}. "
                "Comando destructivo o mala práctica; no se ejecuta por voz. "
                "Si de verdad lo querés, hacelo a mano en una terminal."
            )
    except Exception as exc:  # noqa: BLE001 - último recurso: un bug del guard no puede fallar abierto
        # Esto es un BUG NUESTRO, no un ataque. Se deniega igual (fail-closed) pero se grita,
        # para poder distinguir una cosa de la otra en el log.
        print(f"guard: EXCEPCIÓN INESPERADA (bug del guard) -> DENY: {exc!r}", file=sys.stderr)
        _deny("El guard de seguridad falló al evaluar el comando. Denegado por precaución.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
