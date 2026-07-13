"""Property-based tests (Hypothesis) — Ciclo 9 / U1.

Cada test verifica una PROPIEDAD que debe valer para TODO input, no un caso puntual.
Mapa: P1-P10 de construction/U1-tests-ci/functional-design/business-rules.md.

Perfiles (PBT-08): `default` (100 ejemplos, CI) y `thorough` (1000, propiedades de seguridad).
Correr profundo:  HYPOTHESIS_PROFILE=thorough .venv/bin/pytest tests/test_properties.py
"""

import base64
import json
import os
import sys
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orb.orb_server import VALID_STATES, normalize_state  # noqa: E402
from vc import attach, guard, session  # noqa: E402
from tests import generators as gen  # noqa: E402

# --- Perfiles de Hypothesis (PBT-08) ---
# too_slow suprimido: el primer test de la corrida paga el warm-up del generador (cold start,
# ~1.4s la primera vez), que en un runner de CI compartido dispara un falso positivo. No es
# lentitud de generación real (los generadores son triviales); es JIT/import de arranque.
_SUPPRESS = [HealthCheck.too_slow]
settings.register_profile("default", max_examples=100, suppress_health_check=_SUPPRESS)
settings.register_profile("thorough", max_examples=1000, suppress_health_check=_SUPPRESS)
settings.load_profile("thorough" if os.environ.get("HYPOTHESIS_PROFILE") == "thorough" else "default")


# =========================================================================
# P1 + P2 — normalize_state: invariante de rango + idempotencia
# =========================================================================
class TestNormalizeState:
    @given(gen.orb_states())
    def test_p1_always_valid_never_raises(self, name):
        """P1: para CUALQUIER entrada, el resultado pertenece a VALID_STATES. Nunca lanza."""
        result = normalize_state(name)
        assert result in VALID_STATES

    @given(gen.orb_states())
    def test_p2_idempotent(self, name):
        """P2: normalize_state(normalize_state(x)) == normalize_state(x)."""
        once = normalize_state(name)
        assert normalize_state(once) == once


# =========================================================================
# P3 + P4 — Socket de control: round-trip base64 + framing inviolable
# =========================================================================
class TestSocketFraming:
    @given(gen.socket_payloads())
    def test_p3_base64_roundtrip(self, payload):
        """P3: b64decode(b64encode(x)) == x para bytes arbitrarios."""
        assert base64.b64decode(base64.b64encode(payload)) == payload

    @settings(max_examples=1000 if os.environ.get("HYPOTHESIS_PROFILE") == "thorough" else 200)
    @given(gen.socket_payloads())
    def test_p4_no_newline_in_payload(self, payload):
        """P4 (SEGURIDAD): el base64 del payload NUNCA contiene '\\n'.

        El socket de control usa readline() como framing (`verbo <b64>\\n`). Si el payload
        pudiera contener un salto de línea, un adjunto malicioso partiría el mensaje e
        inyectaría un comando en el socket del agente. b64encode (≠ encodebytes) no emite
        saltos: esta propiedad clava ese contrato para que nadie lo rompa en silencio.
        """
        assert b"\n" not in base64.b64encode(payload)


# =========================================================================
# P5 + P6 — Config: parser robusto + settings idempotente (I/O -> deadline=None)
# =========================================================================
class TestConfigRobustness:
    @settings(deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(content=gen.blacklist_file_contents())
    def test_p5_blacklist_parser_never_crashes(self, tmp_path, content):
        """P5: para CUALQUIER contenido de archivo, el parser devuelve list[str] y NUNCA lanza.
        Corre en el arranque de saga: si lanzara, saga no levanta.

        RESUELTO (F1, Ciclo 9/U1): _read_plugins_blacklist ahora guarda contra `items` no-lista
        (`{"disabledPlugins": 42}` ya no crashea). Antes lanzaba TypeError en el arranque."""
        import vc.config as config
        f = tmp_path / "blacklist.json"
        f.write_bytes(content)
        orig = config.PLUGINS_BLACKLIST
        config.PLUGINS_BLACKLIST = f
        try:
            result = config._read_plugins_blacklist()
        finally:
            config.PLUGINS_BLACKLIST = orig
        assert isinstance(result, list)
        assert all(isinstance(x, str) for x in result)

    @settings(deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(plugins=st.lists(st.text(min_size=1, max_size=20), max_size=6))
    def test_p6_ensure_settings_idempotent(self, tmp_path, plugins):
        """P6: _ensure_saga_settings aplicado dos veces == una vez (mismo contenido)."""
        import vc.config as config
        settings_path = tmp_path / ".saga-settings.json"
        orig_path, orig_disabled = config.SAGA_SETTINGS, config.DISABLED_PLUGINS
        config.SAGA_SETTINGS = settings_path
        config.DISABLED_PLUGINS = plugins
        try:
            config._ensure_saga_settings()
            first = settings_path.read_text()
            config._ensure_saga_settings()
            second = settings_path.read_text()
        finally:
            config.SAGA_SETTINGS, config.DISABLED_PLUGINS = orig_path, orig_disabled
        assert first == second
        assert json.loads(first)["hooks"]["PreToolUse"]  # el guard siempre queda cableado


# =========================================================================
# P7 + P8 — Guard: bloquea lo catastrófico / NO bloquea lo legítimo
# =========================================================================
class TestGuard:
    @pytest.mark.xfail(
        reason="P7/Q3=A: la denylist regex actual es evadible por construcción. Hypothesis "
        "encuentra bypasses (p.ej. 'rm -r -f /', flags separadas). Es el hallazgo esperado; "
        "el endurecimiento del guard es U3 (FR2.2). Cuando U3 cierre los bypasses, pasa a verde.",
        strict=True,
    )
    @settings(max_examples=1000 if os.environ.get("HYPOTHESIS_PROFILE") == "thorough" else 200)
    @given(gen.catastrophic_commands())
    def test_p7_blocks_catastrophic(self, cmd):
        """P7 (SEGURIDAD): un comando catastrófico debe ser bloqueado (denied != None).

        ⚠️ SE ESPERA QUE ESTE TEST FALLE (Q3=A). La denylist actual es evadible: `rm -r -f`
        (flags separadas) no matchea el regex `\\brm\\s+-[a-z]*r[a-z]*f`. El contraejemplo
        que encuentre Hypothesis es un BYPASS REAL, input directo para U3 (endurecimiento
        del guard). NO se arregla el guard acá: es territorio de U3.
        """
        label = guard.denied(cmd)
        assert label is not None, f"BYPASS del guard (input para U3): {cmd!r} no fue bloqueado"

    @given(gen.benign_commands())
    def test_p8_allows_benign(self, cmd):
        """P8: un comando legítimo NO debe ser bloqueado. Un falso positivo = guard que
        se termina desactivando = sin guard."""
        assert guard.denied(cmd) is None, f"falso positivo del guard: {cmd!r} fue bloqueado"


# =========================================================================
# P9 — attach: máquina de estados + consume-once (stateful, PBT-06)
# =========================================================================
class TestAttachStateful:
    @given(st.lists(st.one_of(
        st.tuples(st.just("stage"), st.text(max_size=30)),
        st.just(("clear", None)),
        st.just(("take", None)),
    ), max_size=20))
    def test_p9_matches_reference_model(self, ops):
        """P9: tras cualquier secuencia de stage/clear/take, el texto observable coincide
        con un modelo de referencia (Optional[str]). Incluye consume-once."""
        attach.clear_text()
        model = None  # modelo de referencia
        try:
            for op, arg in ops:
                if op == "stage":
                    attach.stage_text(arg)
                    model = arg.strip() or None
                elif op == "clear":
                    attach.clear_text()
                    model = None
                else:  # take
                    got_txt, _ = attach.take_staged()
                    assert got_txt == model, f"divergencia del modelo tras {op}: {got_txt!r} != {model!r}"
                    model = None  # consume-once: quedó vacío
        finally:
            attach.clear_text()


# =========================================================================
# P10 — Keywords de sesión: nunca lanzan, respetan límites de palabra
# =========================================================================
class TestSessionKeywords:
    @given(st.text())
    def test_p10_never_raises(self, text):
        """P10: is_reset_command / is_visual_command nunca lanzan, para cualquier string."""
        assert isinstance(session.is_reset_command(text), bool)
        assert isinstance(session.is_visual_command(text), bool)
