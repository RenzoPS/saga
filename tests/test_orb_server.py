"""Tests de ejemplo de la superficie HTTP de orb_server (Ciclo 9 / U1).

Complementan a los PBT (PBT-10): fijan comportamiento concreto y conocido.

⚠️ Dos de estos tests documentan el ESTADO ACTUAL (inseguro) y están DISEÑADOS para
cambiar en U2 (auth por default). Cuando cambien, ESE cambio es la evidencia de que
el agujero S5/S6 se cerró.
"""

import http.client
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orb import orb_server  # noqa: E402


@pytest.fixture
def server():
    """Levanta orb_server en un puerto libre (0) y lo tumba limpio."""
    srv = ThreadingHTTPServer(("127.0.0.1", 0), orb_server.Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield port
    finally:
        srv.shutdown()
        srv.server_close()


def _get(port, path):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("GET", path)
    r = c.getresponse()
    body = r.read()
    c.close()
    return r.status, body


def _post(port, path, body=b""):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("POST", path, body=body)
    r = c.getresponse()
    r.read()
    c.close()
    return r.status


# --- Routing ---
def test_healthz_ok(server):
    status, body = _get(server, "/healthz")
    assert status == 200
    assert body == b"ok"


def test_unknown_route_404(server):
    status, _ = _get(server, "/no-existe")
    assert status == 404


# --- Auth (estado ACTUAL; U2 lo endurece) ---
def test_auth_rejects_without_token_when_token_set(server, monkeypatch):
    """Con ORB_TOKEN seteado, un POST sin token -> 403. Esta es la defensa que YA existe
    cuando el token está configurado."""
    monkeypatch.setattr(orb_server, "TOKEN", "secreto-de-prueba")
    status = _post(server, "/state?s=idle")
    assert status == 403


@pytest.mark.xfail(
    reason="S5: HOY orb_server no exige auth por default (ORB_TOKEN vacío). "
    "U2 (FR3.1) debe invertir esto -> cuando pase a 403, el agujero está cerrado.",
    strict=True,
)
def test_no_auth_by_default_is_the_hole(server, monkeypatch):
    """⚠️ DOCUMENTA EL AGUJERO S5. Con ORB_TOKEN vacío (default de hoy), _authorized()
    devuelve True y un POST sin token PASA. El test afirma la conducta SEGURA (rechazo);
    hoy FALLA a propósito (xfail strict). U2 lo hace pasar."""
    monkeypatch.setattr(orb_server, "TOKEN", "")
    status = _post(server, "/state?s=idle")
    assert status == 403, "sin auth: el POST no fue rechazado (agujero S5, lo cierra U2)"


# --- Path traversal en /vendor (defensa existente) ---
def test_vendor_path_traversal_blocked(server):
    status, _ = _get(server, "/vendor/../../etc/passwd")
    assert status in (403, 404)   # la resolución de path lo saca del árbol de VENDOR


# --- /token sin credenciales -> 500 con mensaje, sin filtrar secretos ---
def test_token_without_livekit_keys_500(server, monkeypatch):
    monkeypatch.setattr(orb_server, "LIVEKIT_API_KEY", "")
    monkeypatch.setattr(orb_server, "LIVEKIT_API_SECRET", "")
    status, _ = _get(server, "/token?identity=x")
    assert status == 500
