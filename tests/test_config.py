"""Tests de ejemplo de vc/config.py (Ciclo 9 / U1).

⚠️ test_god_mode_by_default documenta el ESTADO ACTUAL (S1: --dangerously-skip-permissions
por default). Está DISEÑADO para cambiar en U3. Cuando cambie, ese cambio es la evidencia
de que el god-mode se fue.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import vc.config as config  # noqa: E402


# --- build_claude_base_args: estado actual (god-mode) ---
@pytest.mark.xfail(
    reason="S1: HOY el daemon corre con --dangerously-skip-permissions por default. "
    "U3 (FR2.1) lo reemplaza por --permission-mode auto -> cuando el flag desaparezca, "
    "el god-mode se fue.",
    strict=True,
)
def test_no_god_mode_by_default():
    """⚠️ DOCUMENTA EL AGUJERO S1. Afirma la conducta SEGURA (sin skip-permissions);
    hoy FALLA a propósito (xfail strict). U3 lo hace pasar."""
    args = config.build_claude_base_args("test-session-id", "--session-id")
    assert "--dangerously-skip-permissions" not in args


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
