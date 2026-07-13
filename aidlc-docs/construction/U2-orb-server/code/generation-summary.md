# U2 — Code Generation Summary

**Unidad**: U2 — Hardening de `orb_server` (FR3.1 … FR3.7) · **Rama**: `feature/ciclo9-u2-orb-server`

## Archivos tocados

| Archivo | Cambio | FR |
|---|---|---|
| `vc/config.py` | `orb_token()` / `reset_orb_token()` — fuente única del token en `XDG_RUNTIME_DIR/saga/orb-token` (`0600`, `O_CREAT\|O_EXCL`, `secrets.token_urlsafe(32)`) | FR3.1 |
| `orb/orb_server.py` | **la puerta `_gate()`** (Host → healthz → token → tamaño, fail-closed) · `_authorized()` con `hmac.compare_digest` + guarda `TypeError` · headers de seguridad · cero CORS · `/token` con TTL 5min + grants mínimos + `room`/`identity` del server | FR3.1-3.7 |
| `orb/orb.html` | lee `?token=` → memoria + `history.replaceState` · `EventSource('/events?token=')` · `__orbFetch` con `X-Orb-Token` en los 4 `fetch` | FR3.1, FR3.6 |
| `vc/orb.py` | `orb_url_with_token()` · el `POST /state` del agente manda `X-Orb-Token` · `ensure_orb` pasa el token por env y abre el browser con `?token=` | FR3.1 |
| `vcctl.py` | `reset_orb_token()` en `start` (rotación por arranque) y en `stop` · `xdg-open` con `?token=` (sin imprimir el token en consola) | FR3.1 |
| `tests/generators.py` | `adversarial_hosts()` — hosts de bypass de substring | PBT-01 |
| `tests/test_orb_server.py` | des-marcado el xfail S5 · 6 propiedades U2-P1…U2-P6 + ejemplos | PBT-01 |

## Decisión de arquitectura del token (leída del código)
El token lo necesitan **3 procesos**: `orb_server` (valida), el browser (cliente), y **el agente**
(`vc/orb.py` hace `POST /state` desde el worker, otro proceso). Un token en memoria no le llega a los
tres → **archivo de runtime `0600`** en `XDG_RUNTIME_DIR` (tmpfs, `0700`, muere con la sesión). Patrón
del runtime dir de Jupyter. Rotado por arranque (efímero).

## Hallazgo (el valor del PBT)
**U2-P6 cazó un bug de robustez real**: `hmac.compare_digest` **tira `TypeError` con strings
no-ASCII**. Un token Unicode por `?token=` **crasheaba el handler** en vez de rechazar (fail-open por
excepción). Corregido: `try/except TypeError → False` (fail-closed). Un test de ejemplo no lo hubiera
encontrado; Hypothesis generó `'Ā'`.

## Verificación estática (CERRADA)
- **pytest**: `tests/test_orb_server.py` **15 passed**. Suite completa **43 passed, 2 xfailed**
  (los 2 xfail restantes son de U3: S1 god-mode y P7 guard — intactos). **El xfail de S5 se
  des-marcó** y ahora son tests reales que pasan.
- **thorough** (1000 ejemplos en P1/P2/P6): `test_properties + test_orb_server` **24 passed, 1 xfailed**.
- **ruff**: limpio. · **mypy** (`orb_server`, `config`): limpio.
- **py_compile** + **import smoke** de los 3 procesos: OK.
- Verificación manual con `curl` contra el server real: healthz 200 · sin token 401 · `/token` sin
  token 401 (era abierto) · **rebinding con token válido 403** (el Host gana) · `/say` sin token 401 ·
  attach >10MB 413 · sin headers CORS.

## Pendiente (único): validación EN VIVO del usuario — C1
Cambio **atómico** server+cliente+agente. Falta arrancar saga y confirmar el **turno de voz completo**
(el orbe conecta, cambia de estado, responde por voz). Es el riesgo #1 (C1): si el token no fluye, el
orbe queda mudo.
