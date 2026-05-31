#!/usr/bin/env python3
"""PreToolUse hook: bloquea comandos Bash CATASTRÓFICOS/irreversibles antes de
ejecutarlos. god-mode + voz = un mishear no puede borrar el disco ni reventar
el sistema. Permite TODO lo demás (incluido sudo install, builds, git normal).

Protocolo Claude Code PreToolUse: lee JSON por stdin con {tool_name, tool_input}.
Para bloquear: stdout JSON con permissionDecision=deny (exit 0). Los hooks corren
aún con --dangerously-skip-permissions (el bypass salta prompts, no hooks).

Fail-open a propósito: si el input no parsea, NO bloquea (no brickear el agente
por un hiccup del hook). La denylist es defensa contra desastres, no un sandbox.
"""

import sys
import json
import re

# (patrón regex, etiqueta legible). Solo lo verdaderamente catastrófico/irreversible
# que JAMÁS comandarías por voz a propósito. NO incluye sudo/install/build/git normal.
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


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0  # fail-open: input raro -> no bloqueo (no romper el agente)

    if data.get("tool_name") != "Bash":
        return 0
    cmd = ((data.get("tool_input") or {}).get("command") or "")

    for pat, label in DENY:
        if re.search(pat, cmd, re.IGNORECASE):
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f"Bloqueado por seguridad de voz: {label}. "
                    "Comando destructivo no permitido por voz; si de verdad lo querés, hacelo a mano en una terminal."
                ),
            }}))
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
