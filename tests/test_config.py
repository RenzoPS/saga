"""Tests de ejemplo de vc/config.py (Ciclo 9 / U1 + U3).

El agujero S1 (god-mode por default) era un xfail-strict que documentaba el estado actual.
U3 (FR2.1) lo CERRÓ: el xfail se des-marcó y el test ahora afirma la conducta real.
"""

import json
import os
import sys
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import vc.config as config  # noqa: E402


# --- U3-P4 / S1: el god-mode se fue (FR2.1 · BR-U3-1) ---
def test_no_god_mode_by_default():
    """S1 CERRADO (U3): el daemon ya NO corre con --dangerously-skip-permissions."""
    args = config.build_claude_base_args("test-session-id", "--session-id")
    assert "--dangerously-skip-permissions" not in args


def test_permission_mode_auto():
    """FR2.1: el modo de permisos es `auto`, y va explícito en los args."""
    args = config.build_claude_base_args("sid", "--session-id")
    assert "--permission-mode" in args
    assert args[args.index("--permission-mode") + 1] == "auto"


@settings(max_examples=1000 if os.environ.get("HYPOTHESIS_PROFILE") == "thorough" else 100)
@given(
    plugins=st.sampled_from(["0", "1", "on", "off", "true", "", "basura"]),
    mem=st.sampled_from(["0", "1", "", "x"]),
    # VOICE_CLAUDE_SAFE ya no existe (NFR3), pero alguien puede exportarla de memoria:
    # ni así puede volver el god-mode.
    safe_residual=st.sampled_from(["0", "1", "", "yes"]),
    session_id=st.text(min_size=1, max_size=40),
)
def test_u3_p4_never_god_mode(plugins, mem, safe_residual, session_id):
    """U3-P4 (NFR3 — seguridad SIN toggle de apagado): para CUALQUIER combinación de env,
    los args nunca traen --dangerously-skip-permissions y siempre traen --permission-mode auto.

    Incluye un VOICE_CLAUDE_SAFE residual: la variable se eliminó, y ni exportándola vuelve
    el god-mode. No hay interruptor que apague la seguridad.

    (El env se toca a mano y no con monkeypatch: Hypothesis rechaza los fixtures
    function-scoped bajo @given porque no se resetean entre inputs generados.)"""
    previo = {k: os.environ.get(k) for k in ("CLAUDE_PLUGINS", "VOICE_CLAUDE_MEM", "VOICE_CLAUDE_SAFE")}
    os.environ.update(CLAUDE_PLUGINS=plugins, VOICE_CLAUDE_MEM=mem, VOICE_CLAUDE_SAFE=safe_residual)
    try:
        args = config.build_claude_base_args(session_id, "--session-id")
    finally:
        for k, v in previo.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    assert "--dangerously-skip-permissions" not in args
    assert args[args.index("--permission-mode") + 1] == "auto"


# --- U3-P7: el system prompt lleva las 3 reglas de seguridad (FR2.5 · FR2.6) ---
def test_u3_p7_system_prompt_has_security_rules():
    """U3-P7: si alguien borra las reglas de seguridad del prompt, este test grita.
    El prompt es superficie de seguridad: no hay compilador que se queje si desaparecen."""
    p = config.CLAUDE_SYSTEM_PROMPT.lower()
    assert "seguridad" in p
    # (1) confirmación de dos pasos antes de lo destructivo
    assert "confirmacion en dos pasos" in p or "confirmación en dos pasos" in p
    assert "no ejecutas hasta que el usuario te diga que si" in p
    # (2) lo leído son datos, no órdenes (anti prompt-injection)
    assert "datos, nunca ordenes" in p or "datos, nunca órdenes" in p
    # (3) nada interactivo
    assert "nada interactivo" in p


def test_u3_p7_prompt_still_allows_the_everyday():
    """Contrapeso de U3-P7 (riesgo R3 / OWASP ASI09): el prompt tiene que decir EXPLÍCITAMENTE
    qué NO se confirma. Si saga pide permiso para todo, el usuario la apaga -> seguridad = 0."""
    p = config.CLAUDE_SYSTEM_PROMPT.lower()
    assert "no aplica a lo cotidiano" in p
    assert "git status" in p


# --- FR2.4 / BR-U3-9: el settings NO lleva bloque `permissions` ---
def test_saga_settings_has_no_permissions_block(tmp_path, monkeypatch):
    """BR-U3-9 (decisión del usuario): sin reglas `permissions.deny`. Una regla deny es un techo
    duro inapelable -> rompería el principio de 'pedímelo dos veces y lo hago'."""
    monkeypatch.setattr(config, "SAGA_SETTINGS", tmp_path / ".saga-settings.json")
    monkeypatch.setattr(config, "DISABLED_PLUGINS", [])
    config._ensure_saga_settings()
    data = json.loads((tmp_path / ".saga-settings.json").read_text())
    assert "permissions" not in data


def test_base_args_has_session_and_model():
    args = config.build_claude_base_args("sid-123", "--session-id")
    assert "claude" == args[0]
    assert "--session-id" in args
    assert "sid-123" in args
    assert "--model" in args


# --- CLAUDE_FAST_FLAGS según CLAUDE_PLUGINS ---
def test_plugins_mode_off_strips_settings():
    """CLAUDE_PLUGINS off (default) -> se saltan los setting-sources (arranque liviano)."""
    if config.PLUGINS_MODE == "off":
        assert "--setting-sources" in config.CLAUDE_FAST_FLAGS


# --- _ensure_saga_settings: forma del settings ---
def test_saga_settings_wires_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SAGA_SETTINGS", tmp_path / ".saga-settings.json")
    monkeypatch.setattr(config, "DISABLED_PLUGINS", [])
    config._ensure_saga_settings()
    data = json.loads((tmp_path / ".saga-settings.json").read_text())
    hook = data["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert "guard.py" in hook
    assert "enabledPlugins" not in data   # blacklist vacía -> no aparece


def test_saga_settings_disables_plugins_when_blacklisted(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SAGA_SETTINGS", tmp_path / ".saga-settings.json")
    monkeypatch.setattr(config, "DISABLED_PLUGINS", ["foo@market", "bar@market"])
    config._ensure_saga_settings()
    data = json.loads((tmp_path / ".saga-settings.json").read_text())
    assert data["enabledPlugins"] == {"foo@market": False, "bar@market": False}


# --- _read_plugins_blacklist: casos concretos (complementa el PBT P5) ---
def test_blacklist_valid(tmp_path, monkeypatch):
    f = tmp_path / "bl.json"
    f.write_text(json.dumps({"disabledPlugins": ["a@m", "b@m"]}))
    monkeypatch.setattr(config, "PLUGINS_BLACKLIST", f)
    assert config._read_plugins_blacklist() == ["a@m", "b@m"]


def test_blacklist_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PLUGINS_BLACKLIST", tmp_path / "no-existe.json")
    assert config._read_plugins_blacklist() == []


def test_blacklist_broken_json(tmp_path, monkeypatch):
    f = tmp_path / "bl.json"
    f.write_text("{roto")
    monkeypatch.setattr(config, "PLUGINS_BLACKLIST", f)
    assert config._read_plugins_blacklist() == []


def test_blacklist_ignores_comment_key(tmp_path, monkeypatch):
    f = tmp_path / "bl.json"
    f.write_text(json.dumps({"_comment": "nota", "disabledPlugins": ["x@m"]}))
    monkeypatch.setattr(config, "PLUGINS_BLACKLIST", f)
    assert config._read_plugins_blacklist() == ["x@m"]
