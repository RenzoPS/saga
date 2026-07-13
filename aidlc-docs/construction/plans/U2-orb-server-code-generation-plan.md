# U2 — Code Generation Plan (Part 1)

**Unidad**: U2 — Hardening de `orb_server` (FR3.1 … FR3.7) · **Rama**: `feature/ciclo9-u2-orb-server`
**Riesgo**: Medio — **C1 (atómico)**: si el server exige token y el cliente no lo manda, **saga queda muda**.

---

## Hallazgo de arquitectura (leído del código, cambia el diseño del token)

El token lo necesitan **TRES procesos distintos**, no dos:

| Proceso | Rol | Cómo obtiene el token |
|---|---|---|
| `orb/orb_server.py` | **valida** | env `ORB_TOKEN` (lo pone quien lo lanza) |
| `orb/orb.html` (browser) | cliente | `?token=` en la URL que abre `xdg-open` |
| **`vc/orb.py` `_OrbClient`** | **`POST /state` en cada transición del orbe** | **corre DENTRO del worker (`lk/agent.py`) — otro proceso** |

**Consecuencia**: un token en memoria de `vcctl` **no le llega al agente**. Y `ensure_orb()`
(`vc/orb.py:26`) puede levantar el server **desde el propio agente**, no solo desde `vcctl`.

**Solución (patrón Jupyter runtime dir)**: un **archivo de token** en `XDG_RUNTIME_DIR/saga/orb-token`,
modo **`0600`**.
- `XDG_RUNTIME_DIR` (`/run/user/1000`) es **tmpfs y `0700`** → no toca el disco, muere con la sesión.
- **Fuente única**: cualquiera de los tres lo lee de ahí.
- **Rotación**: `saga-ctl start` **borra el archivo** antes de levantar → **token nuevo por arranque**
  (efímero, D2 del Functional Design). `stop` también lo borra.
- **Race-safe**: creación con `O_CREAT|O_EXCL`; si otro proceso ganó, se relee.

---

## Pasos

### Paso 1 — `vc/config.py`: fuente única del token
- [ ] `ORB_TOKEN_FILE = XDG_RUNTIME_DIR/saga/orb-token` (fallback `/tmp/saga-<uid>/` si no existe la var).
- [ ] `orb_token() -> str`: lee el archivo; si no existe, lo **crea** con `secrets.token_urlsafe(32)`
      (`O_CREAT|O_EXCL`, `0600`); si perdió la carrera, relee.
- [ ] `reset_orb_token()`: borra el archivo (lo llama `saga-ctl start`/`stop` → rotación).
- **Sin dependencias nuevas**: `secrets` es stdlib.

### Paso 2 — `orb/orb_server.py`: la puerta (el grueso de la unidad)
- [ ] `TOKEN`: del env `ORB_TOKEN`; si viene vacío → **`orb_token()`** (BR-2: **vacío ya no es "sin auth"**).
- [ ] `_ALLOWED_HOSTS = frozenset({f"127.0.0.1:{PORT}", f"localhost:{PORT}", f"[::1]:{PORT}"})`.
- [ ] **`_gate()`** — puerta única, en **este orden** (BR-1, BR-4, BR-6):
      1. `Host` ∉ allowlist **exacta** → **403** (anti-rebinding; **va primero**)
      2. ruta `/healthz` → pasa (única exenta)
      3. token (header `X-Orb-Token` **o** `?token=`) con **`hmac.compare_digest`** → si no → **401**
      4. `Content-Length > límite(ruta)` → **413** **sin leer el body**
- [ ] Llamarla **al principio de `do_GET` y de `do_POST`** (hoy `_authorized()` solo se llama en
      `do_POST` → `/token` y `/events` quedaban abiertos).
- [ ] **Borrar** los dos `Access-Control-Allow-Origin: *` (líneas 188 y 283) — **BR-5**.
- [ ] `_send_bytes()` + `_serve_events()` + `_ok204()`: agregar los **headers de seguridad** (`nosniff`,
      `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, CSP `frame-ancestors 'none'; form-action
      'none'; base-uri 'none'`).
- [ ] `_serve_token()`: **`identity` y `room` del SERVER** (ignorar el query — BR-7) + **TTL 5 min** +
      **grants mínimos** (`can_publish_sources=["microphone"]`, `can_publish_data=False`,
      `can_update_own_metadata=False`) — BR-8.
- [ ] `LIMITS = {"/attach": 10MB, "/say": 64KB, "/stage": 64KB}`, default **8 KB**.

### Paso 3 — `orb/orb.html`: el cliente (C1 — atómico con el Paso 2)
- [ ] Al cargar: leer `?token=` de la URL → guardar en memoria JS → **`history.replaceState`** (saca el
      token de la barra de direcciones).
- [ ] `EventSource('/events?token=' + T)` (línea 133) — **el SSE no acepta headers custom**.
- [ ] Los 4 `fetch` (`/stage`, `/say`, `/attach`, `/token`) → header **`X-Orb-Token`**.

### Paso 4 — `vc/orb.py`: el agente y el arranque
- [ ] `_OrbClient._post()`: mandar el header **`X-Orb-Token`** (es el `POST /state` del agente).
- [ ] `ensure_orb()`: pasar `ORB_TOKEN` en el env del server + abrir el browser con **`?token=`**.

### Paso 5 — `vcctl.py`
- [ ] `_start_room()`: **`reset_orb_token()`** antes de levantar (rotación por arranque) y abrir el
      browser con **`?token=`** (línea 342).
- [ ] `stop`: borrar el archivo del token.
- [ ] El probe de readiness usa `_port_up()` (TCP puro) → **no necesita token**. `/healthz` sigue
      exento igual (lo usa `_orb_up()` en `vc/orb.py:20`).

### Paso 6 — Tests (PBT-01: las 6 propiedades)
- [ ] **Des-marcar el `xfail`** de `test_no_auth_by_default_is_the_hole` (S5) → hará **XPASS**.
- [ ] `tests/generators.py`: generador de **hosts adversariales** (`127.0.0.1.evil.com`,
      `127.0.0.1:8777.evil.com`, …).
- [ ] `tests/test_orb_server.py`: **U2-P1 … U2-P6** con Hypothesis (perfil `thorough`: son todas de
      seguridad).

### Paso 7 — Verificación estática
- [ ] `pytest` (los 33 de U1 siguen verdes + los nuevos) · `ruff` · `mypy` (`orb_server` **ya** está en
      el scope de mypy desde U1) · `py_compile`.

---

## Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| **C1 — el orbe no conecta → saga muda** | Cambio **atómico** (server + cliente + agente en el mismo commit) + **validación en vivo obligatoria** |
| El agente no manda el token → el orbe **no cambia de estado** (queda clavado en `idle`) | Paso 4. Se ve en vivo al toque: el orbe no reacciona |
| `XDG_RUNTIME_DIR` no existe (cron, contenedor) | Fallback a `/tmp/saga-<uid>/` con `0700` |
| Una pestaña vieja tras reiniciar → **401** | Es el comportamiento **deseado** (falla ruidosa). `saga-ctl` reabre el browser solo |
| La CSP rompe el WebRTC | **Imposible por diseño**: la CSP **no toca** `script-src` ni `connect-src` (BR-10) |

**NFR1**: el hot path del turno **no pasa por HTTP** salvo `POST /state`. El costo agregado es un
lookup en un `frozenset` + un `compare_digest` + un `int()` → **microsegundos**. `/events` se
autentica **una vez** (long-lived).
