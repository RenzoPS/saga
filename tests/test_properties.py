"""Property-based tests (Hypothesis) — Ciclo 9 / U1.

Cada test verifica una PROPIEDAD que debe valer para TODO input, no un caso puntual.
Mapa: P1-P10 de construction/U1-tests-ci/functional-design/business-rules.md.

Perfiles (PBT-08): `default` (100 ejemplos, CI) y `thorough` (1000, propiedades de seguridad).
Correr profundo:  HYPOTHESIS_PROFILE=thorough .venv/bin/pytest tests/test_properties.py
"""

import base64
import json
import os
import re
import subprocess
import sys
from pathlib import Path

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
    @settings(max_examples=1000 if os.environ.get("HYPOTHESIS_PROFILE") == "thorough" else 200)
    @given(gen.catastrophic_commands())
    def test_p7_blocks_catastrophic(self, cmd):
        """P7 / U3-P1 (SEGURIDAD): un comando catastrófico debe ser bloqueado, escrito COMO SEA.

        Era xfail-strict en U1/U2: la denylist regex se evadía con `rm -r -f` (flags separadas).
        U3 lo cerró parseando el comando (shlex + normalización de flags) -> el xfail se des-marcó.
        Si este test vuelve a fallar, es que se reabrió un bypass.
        """
        label = guard.denied(cmd)
        assert label is not None, f"BYPASS del guard: {cmd!r} no fue bloqueado"

    @given(gen.benign_commands())
    def test_p8_allows_benign(self, cmd):
        """P8 / U3-P2: un comando legítimo NO debe ser bloqueado. Un falso positivo = guard que
        se termina desactivando = sin guard."""
        assert guard.denied(cmd) is None, f"falso positivo del guard: {cmd!r} fue bloqueado"


# =========================================================================
# U3 — Modelo de permisos (Ciclo 9 / U3)
# =========================================================================
class TestGuardU3:
    @settings(max_examples=1000 if os.environ.get("HYPOTHESIS_PROFILE") == "thorough" else 200)
    @given(gen.git_bad_practice_commands())
    def test_u3_p1_blocks_git_bad_practices(self, cmd):
        """U3-P1 (BR-U3-4b): las MALAS PRÁCTICAS DE GIT se bloquean DURO, en cualquier variante.
        Decisión explícita del usuario: no pasan por confirmación hablada; se hacen a mano."""
        assert guard.denied(cmd) is not None, f"mala práctica de git NO bloqueada: {cmd!r}"

    @settings(max_examples=1000 if os.environ.get("HYPOTHESIS_PROFILE") == "thorough" else 200)
    @given(gen.equivalent_catastrophic_forms())
    def test_u3_p5_flag_forms_are_equivalent(self, forms):
        """U3-P5 (BR-U3-3): el veredicto NO puede depender de CÓMO se escribió el comando.
        `rm -rf X` == `rm -r -f X` == `rm --recursive --force X`. Acá vivían los bypasses:
        el regex miraba el string, no la semántica."""
        verdicts = [guard.denied(f) for f in forms]
        assert all(v is not None for v in verdicts), (
            "formas equivalentes con veredictos distintos (BYPASS): "
            + repr([f for f, v in zip(forms, verdicts) if v is None])
        )

    @settings(max_examples=1000 if os.environ.get("HYPOTHESIS_PROFILE") == "thorough" else 200)
    @given(st.one_of(gen.catastrophic_commands(), gen.benign_commands(),
                     gen.git_bad_practice_commands(), st.text(max_size=80)))
    def test_u3_p6_oracle_no_regression(self, cmd):
        """U3-P6 (ORACLE, PBT-05) — LA PROPIEDAD MÁS IMPORTANTE DE U3.

        El guard NUEVO (parser) debe bloquear TODO lo que bloqueaba el VIEJO (regex).
        El oracle es la denylist regex heredada: si ella dice "catastrófico", el guard nuevo
        NO puede decir que pase. El rewrite puede AGREGAR cobertura, jamás QUITARLA.

        Sin esta propiedad, el rewrite del guard podría ABRIR un agujero que estaba tapado
        y nadie se enteraría hasta que alguien lo explote.
        """
        oracle = None
        for pat, label in guard.DENY:                      # el motor viejo, tal cual
            if re.search(pat, cmd, re.IGNORECASE):
                oracle = label
                break
        if oracle is not None:
            assert guard.denied(cmd) is not None, (
                f"REGRESIÓN: el guard viejo bloqueaba {cmd!r} ({oracle}), el nuevo lo deja pasar"
            )

    # deadline=None: este test lanza un SUBPROCESO por ejemplo (~45ms de arranque de python3).
    # El deadline default de Hypothesis (200ms) lo hace flaky bajo carga -> un timeout en un runner
    # compartido es ruido, no un bug (misma política que P5/P6 en U1). El techo real del guard lo
    # mide el benchmark de Build & Test, no este test.
    @settings(max_examples=1000 if os.environ.get("HYPOTHESIS_PROFILE") == "thorough" else 200,
              suppress_health_check=_SUPPRESS, deadline=None)
    @given(gen.malformed_hook_inputs())
    def test_u3_p3_fail_closed(self, payload):
        """U3-P3 (BR-U3-2 · SECURITY-15 · NFR4): el guard es FAIL-CLOSED.

        Para CUALQUIER entrada (JSON mutilado, tipos cruzados, no-ASCII, raíz equivocada):
        - nunca lanza una excepción no capturada,
        - y si no puede EVALUAR el comando, DENIEGA (no deja pasar).

        El precedente es U2: hmac.compare_digest crasheaba con no-ASCII -> fail-open por
        excepción. Lo cazó una propiedad, no un test de ejemplo.
        """
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parent.parent / "vc" / "guard.py")],
            input=json.dumps(payload), capture_output=True, text=True, timeout=20,
        )
        assert proc.returncode == 0, f"el guard crasheó: {proc.stderr[:200]}"

        salida = proc.stdout.strip()
        decision = None
        if salida:
            decision = json.loads(salida)["hookSpecificOutput"]["permissionDecision"]

        # Si el payload es un Bash bien formado, la decisión la manda `denied()`.
        # Si está mutilado (no se puede evaluar), la ÚNICA salida aceptable es deny.
        evaluable = (
            isinstance(payload, dict)
            and payload.get("tool_name") == "Bash"
            and isinstance(payload.get("tool_input"), dict)
            and isinstance(payload["tool_input"].get("command"), str)
        )
        no_es_bash = (isinstance(payload, dict)
                      and isinstance(payload.get("tool_name"), str)
                      and payload["tool_name"] != "Bash")

        if not evaluable and not no_es_bash:
            assert decision == "deny", f"FAIL-OPEN con payload no evaluable: {payload!r}"


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
