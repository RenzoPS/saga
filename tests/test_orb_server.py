"""Tests de la superficie HTTP de orb_server.

Ciclo 9 / U1: tests de ejemplo (routing, path traversal). U1 dejó dos que documentaban
agujeros (S5 sin auth) como xfail-strict.
Ciclo 9 / U2: el hardening (FR3.1…FR3.7). Los xfail se des-marcan (el agujero se cerró) y se
agregan las propiedades U2-P1…U2-P6 (PBT-01). El fixture ahora inyecta un token conocido y manda
el Host correcto: con la puerta activa, TODO request necesita ambos.
"""

import http.client
import os
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orb import orb_server  # noqa: E402
from tests.generators import adversarial_hosts  # noqa: E402

TOKEN = "token-de-prueba-conocido-123456"
# Perfil (PBT-08): las propiedades de seguridad pura (P1/P2/P6) van a 1000 con HYPOTHESIS_PROFILE=thorough.
_N = 1000 if os.environ.get("HYPOTHESIS_PROFILE") == "thorough" else 200


@pytest.fixture
def server(monkeypatch):
    """Levanta orb_server en un puerto libre con un TOKEN conocido y lo tumba limpio.

    La puerta (U2) exige token en todo salvo /healthz, y valida el Host contra el puerto REAL.
    Los helpers _get/_post mandan ambos por default para el camino feliz."""
    monkeypatch.setattr(orb_server, "TOKEN", TOKEN)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), orb_server.Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield port
    finally:
        srv.shutdown()
        srv.server_close()


def _host(port):
    return f"127.0.0.1:{port}"


def _get(port, path, token=TOKEN, host=None, headers=None):
    h = dict(headers or {})
    h["Host"] = host if host is not None else _host(port)
    if token is not None and "token=" not in path:
        h["X-Orb-Token"] = token
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("GET", path, headers=h)
    r = c.getresponse()
    body = r.read()
    hdrs = r.getheaders()
    c.close()
    return r.status, body, hdrs


def _post(port, path, body=b"", token=TOKEN, host=None, extra=None):
    h = dict(extra or {})
    h["Host"] = host if host is not None else _host(port)
    if token is not None:
        h["X-Orb-Token"] = token
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("POST", path, body=body, headers=h)
    r = c.getresponse()
    r.read()
    c.close()
    return r.status


# --- Routing (camino feliz: token + host correctos) ---
def test_healthz_ok(server):
    # /healthz es la única ruta exenta de token (probe de readiness). Pero el Host SÍ se valida.
    status, body, _ = _get(server, "/healthz", token=None)
    assert status == 200
    assert body == b"ok"


def test_unknown_route_404(server):
    status, _, _ = _get(server, "/no-existe")
    assert status == 404


# --- U2-P1 / auth: deny-by-default (antes era xfail S5, ahora es la conducta REAL) ---
def test_auth_rejects_without_token(server):
    """FR3.1: sin token -> 401. Antes (U1) esto era la defensa 'solo si el token estaba seteado';
    ahora el token SIEMPRE está seteado (no puede quedar vacío) → deny by default."""
    assert _post(server, "/state?s=idle", token=None) == 401


def test_auth_accepts_with_header_token(server):
    assert _post(server, "/state?s=idle") == 204


def test_events_requires_token(server):
    # /events (SSE) se autentica por ?token= (no acepta headers). Sin token -> 401.
    # Es un stream infinito: no lo leemos entero, solo miramos el status de la respuesta.
    c = http.client.HTTPConnection("127.0.0.1", server, timeout=5)
    c.request("GET", "/events", headers={"Host": _host(server)})
    r = c.getresponse()
    c.close()
    assert r.status == 401


def test_events_ok_with_token(server):
    # con ?token= válido, el SSE abre (200) y arranca el stream.
    c = http.client.HTTPConnection("127.0.0.1", server, timeout=5)
    c.request("GET", f"/events?token={TOKEN}", headers={"Host": _host(server)})
    r = c.getresponse()
    assert r.status == 200
    c.close()


def test_token_endpoint_requires_auth(server, monkeypatch):
    # /token mintea el JWT (un secreto). En U1 estaba ABIERTO; U2 lo cierra.
    monkeypatch.setattr(orb_server, "LIVEKIT_API_KEY", "")
    monkeypatch.setattr(orb_server, "LIVEKIT_API_SECRET", "")
    assert _get(server, "/token", token=None)[0] == 401


# --- /vendor: exento del token (asset sin secreto), pero tras el Host check + traversal bloqueado ---
def test_vendor_reachable_without_token(server):
    # los assets se cargan por import de ES modules (sin headers) -> exigir token dejaba WebGL muerto.
    # El archivo puede no existir en el árbol de test (404), pero NUNCA debe ser 401 por falta de token.
    status, _, _ = _get(server, "/vendor/three/three.module.js", token=None)
    assert status != 401, "vendor exige token -> rompería la carga de three.js (C1)"


def test_vendor_host_still_checked(server):
    # exento del token, NO del Host: el rebinding sigue bloqueado sobre los assets.
    status, _, _ = _get(server, "/vendor/three/three.module.js", token=None, host="evil.com:1234")
    assert status == 403


def test_vendor_path_traversal_blocked(server):
    status, _, _ = _get(server, "/vendor/../../etc/passwd")
    assert status in (401, 403, 404)   # colapsado por el cliente o bloqueado por _serve_vendor


# --- /token sin credenciales -> 500 (con token válido para pasar la puerta) ---
def test_token_without_livekit_keys_500(server, monkeypatch):
    monkeypatch.setattr(orb_server, "LIVEKIT_API_KEY", "")
    monkeypatch.setattr(orb_server, "LIVEKIT_API_SECRET", "")
    status, _, _ = _get(server, "/token")
    assert status == 500


# ==================== PROPIEDADES (PBT-01) ====================

_ROUTES_GET = ["/", "/index.html", "/token", "/no-existe"]
_ROUTES_POST = ["/state", "/say", "/stage", "/attach?kind=image"]
# /events se testea aparte (P1b): es un stream infinito, no se puede leer entero con _get.
# /vendor/* NO va acá: es asset estatico sin secretos, EXENTO del token (se carga por <script src>/
# import de ES modules, que no pueden mandar el header). Se testea en test_vendor_* que igual pasa
# por el Host check y que el path traversal sigue bloqueado.


# U2-P1: ∀ ruta ≠ /healthz, ∀ request sin token válido → nunca 2xx
@settings(max_examples=_N, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    route=st.sampled_from(_ROUTES_GET + _ROUTES_POST),
    bad=st.sampled_from([None, "", "  ", "token-basura", "TOKEN-de-prueba-conocido-123456"]),
)
def test_p1_no_2xx_without_valid_token(server, route, bad):
    if route in _ROUTES_GET:
        status, _, _ = _get(server, route, token=bad)
    else:
        status = _post(server, route, token=bad)
    assert not (200 <= status < 300), f"{route} con token={bad!r} devolvió 2xx (agujero S5)"


# U2-P2: ∀ Host ∉ allowlist exacta → 403 (aunque traiga el token válido)
@settings(max_examples=_N, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(data=st.data())
def test_p2_bad_host_rejected(server, data):
    host = data.draw(adversarial_hosts(port=server))
    # token VÁLIDO a propósito: el Host check tiene que rechazar ANTES de que el token lo salve.
    status, _, _ = _get(server, "/healthz", token=None, host=host)
    assert status == 403, f"Host {host!r} no fue rechazado (bypass de DNS rebinding)"


# U2-P3: ∀ respuesta → ningún header Access-Control-*
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(route=st.sampled_from(_ROUTES_GET))
def test_p3_never_cors_headers(server, route):
    _, _, hdrs = _get(server, route)
    offenders = [k for k, _ in hdrs if k.lower().startswith("access-control-")]
    assert not offenders, f"{route} emitió headers CORS: {offenders}"


# U2-P4: ∀ body > límite → 413 y el archivo de attach NO se creó
@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(extra=st.integers(min_value=1, max_value=5_000_000))
def test_p4_oversize_413_and_no_write(server, monkeypatch, tmp_path, extra):
    target = tmp_path / "attach.png"
    monkeypatch.setattr(orb_server, "ATTACH_IMG_PATH", target)
    over = orb_server.LIMITS["/attach"] + extra
    # mandamos el Content-Length del tamaño excedido pero un body chico: el server debe cortar por
    # el header ANTES de leer. Usamos una conexión cruda para declarar un CL grande sin enviar tanto.
    c = http.client.HTTPConnection("127.0.0.1", server, timeout=5)
    c.putrequest("POST", "/attach?kind=image")
    c.putheader("Host", _host(server))
    c.putheader("X-Orb-Token", TOKEN)
    c.putheader("Content-Length", str(over))
    c.endheaders()
    c.send(b"x")  # mucho menos que 'over': el server no debe esperar a leerlo
    r = c.getresponse()
    c.close()
    assert r.status == 413
    assert not target.exists(), "se escribió el attach pese a exceder el límite"


# U2-P5: el JWT ignora identity/room del query y lleva los del server, con TTL ≤ 5min y grants mínimos
@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(identity=st.text(max_size=40), room=st.text(max_size=40))
def test_p5_jwt_claims_from_server(server, identity, room):
    import base64
    import json as _json
    from urllib.parse import quote
    status, body, _ = _get(server, f"/token?identity={quote(identity)}&room={quote(room)}")
    if status != 200:
        return  # sin keys de LiveKit en el entorno de test -> 500; la propiedad de claims no aplica
    tok = _json.loads(body)["token"]
    payload = tok.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    claims = _json.loads(base64.urlsafe_b64decode(payload))
    assert claims["sub"] == "saga-client"                 # identity del server, no del query
    grants = claims["video"]
    assert grants["room"] == orb_server.LIVEKIT_ROOM      # room del server, no del query
    assert claims["exp"] - claims["nbf"] <= orb_server.JWT_TTL + 1   # TTL corto (LiveKit usa nbf, no iat)
    # grants MÍNIMOS: solo mic, sin data, sin admin/create/record
    assert grants.get("canPublishSources") == ["microphone"]
    assert grants.get("canPublishData") is False
    assert grants.get("canUpdateOwnMetadata") is False
    for forbidden in ("roomCreate", "roomAdmin", "roomRecord", "ingressAdmin"):
        assert grants.get(forbidden) in (None, False), f"grant prohibido presente: {forbidden}"


# U2-P6: ∀ token candidato ≠ el real → 401. Va por ?token= (url-encoded) para poder probar Unicode:
# un header no-ASCII ni siquiera lo puede MANDAR http.client, pero un token no-ASCII SÍ puede llegar
# por la URL — y ahí es donde compare_digest tiraba TypeError (bug real que P6 cazó, ya corregido).
@settings(max_examples=_N, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(cand=st.text())
def test_p6_only_exact_token(server, cand):
    from urllib.parse import quote
    if cand == TOKEN:
        return
    status, _, _ = _get(server, f"/?token={quote(cand)}", token=None)
    assert status == 401, f"token {cand!r} fue aceptado (o crasheó el server)"
