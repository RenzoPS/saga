# U2 — Hardening de `orb_server` · Functional Design Plan

**Ciclo**: 9 · **Unidad**: U2 (FR3.1 … FR3.7) · **Rama**: `feature/ciclo9-u2-orb-server`
**Stage**: Functional Design (obligatorio por **PBT-01**)
**Riesgo**: Medio — **C1**: `orb.html` ↔ `orb_server` es un cambio **ATÓMICO**. Si el server exige token y el cliente no lo manda, **el orbe no conecta y saga queda muda**.

## Historial del plan (por qué esta es la v3)
- **v1** — 7 preguntas al usuario. **Descartada**: planteaban **falsas disyuntivas** (token *o* cookie *o* header) y contenían un **supuesto falso** (que un TTL corto de JWT rompería reconexiones).
- **v2** — tras investigar el estándar (`inception/requirements/ciclo9-security-research.md`). **Descartada por el usuario**: *"tampoco armar algo TAN COMPLEJO, es LOCAL"*. Aplicaba el estándar completo (pensado para servers expuestos) a un equipo monousuario.
- **v3 (esta)** — **proporcional**: solo lo que tapa un atacante que **existe de verdad** en local, y que **cuesta poco** (el rendimiento es crucial — NFR1). Lo descartado está **registrado con su porqué** en los requirements (§FR3-OUT), no olvidado.

---

## Los dos atacantes reales

| Atacante | ¿Existe en local? | Qué lo frena |
|---|---|---|
| **Cualquier pestaña abierta** hace `POST /say` → **dispara Claude en god-mode** | **SÍ — pasa HOY** | Token · cero CORS · `form-action 'none'` |
| **DNS rebinding**: eleva al atacante a same-origin y le deja **leer** las respuestas → **se roba el JWT** | **SÍ** — es el CVE de Ollama (exfiltración demostrada por NCC Group) | **`Host` check + token**. `Origin`/CORS **NO** sirven acá |
| Proceso local malicioso | Sí, pero su límite real es el filesystem | Token (nada más lo puede frenar) |

Todo lo demás (rate limit, cookie, CSP con nonce, `Sec-Fetch-Site`, `Origin` check) → **descartado**: su única víctima potencial era **el propio usuario**. Ver requirements §FR3-OUT.

---

## Estado actual del código (leído, no de memoria)

`orb/orb_server.py` (299 líneas, stdlib + `livekit-api` lazy en `/token`):
- **S5 — el agujero raíz**: `TOKEN = os.environ.get("ORB_TOKEN", "")` (línea 44) + `_authorized()` devuelve `True` si `TOKEN` está vacío (líneas 110-111) → **hoy no hay auth en ningún lado**. Y `_authorized()` **ni siquiera se llama en los GET** (solo en `do_POST`, línea 217) → `/token` y `/events` están abiertos incluso con token configurado.
- **S6 — CORS wildcard**: `Access-Control-Allow-Origin: *` en `/events` (línea 188) y en `_ok204()` (línea 283).
- **S8 — inputs sin validar**: `identity` y `room` salen del query (líneas 151-152) y **se firman en el JWT** (línea 158). `/attach` escribe el body a `/tmp` (**tmpfs = RAM**) **sin límite** (líneas 220-221, 272).
- **S10 — JWT sin TTL** (línea 158): hereda el default del SDK (6h) y **no restringe los grants**.

Cliente (`orb/orb.html`): `EventSource('/events')` + `fetch('/stage'|'/say'|'/attach')` + `fetch('/token?...')`. **Ninguno manda token hoy.** La página la abre `vcctl.py:342` con `xdg-open ORB_URL`.

Red que ya espera (U1): `test_no_auth_by_default_is_the_hole` es **xfail-strict** → al cerrar FR3.1 hará **XPASS** y obligará a des-marcarlo.

---

## Decisiones de diseño (D1–D7)

| # | Decisión | Justificación | Costo |
|---|---|---|---|
| **D1** | **Token único, obligatorio en todo** salvo `/healthz`. Dos vías: `?token=` (bootstrap `GET /` y **`GET /events`**) y header `X-Orb-Token` (los `fetch`). `hmac.compare_digest`. | El `EventSource` **no acepta headers custom** (MDN) → el query param no es una elección, es la única vía. El header en los `fetch` además **fuerza el preflight**. | 1 función |
| **D2** | **Token efímero por arranque**: `vcctl` genera `secrets.token_urlsafe(32)`, lo pasa por env y abre el browser con `?token=`. **No toca el disco.** | Nada que robar del filesystem. `saga-ctl` ya abre el browser solo → en la práctica no se nota. | ~3 líneas |
| **D3** | **Cero headers `Access-Control-*`** | Es **borrar 2 líneas** de deuda. | −2 líneas |
| **D4** | **`Host` check** con allowlist **exacta**, **primero de todo** | **Anti-DNS-rebinding.** Match exacto: `"127.0.0.1" in host` deja pasar `127.0.0.1.evil.com`. | ~5 líneas |
| **D5** | **Headers**: `nosniff` · `X-Frame-Options: DENY` · `Referrer-Policy: no-referrer` · CSP = `frame-ancestors 'none'; form-action 'none'; base-uri 'none'` | La CSP **no toca `script-src` ni `connect-src`** → **no puede romper el WebRTC ni el JS inline**. `form-action 'none'` mata el `POST` por `<form>`, **el único CSRF que el header custom no frena**. | 4 líneas |
| **D6** | **Límites**: `/attach` 10 MB · `/say`+`/stage` 64 KB · resto 8 KB → **413 sin leer el body** | Hoy `/attach` escribe a **tmpfs (RAM)** sin cap. Cortar antes de leer = no se toca RAM ni disco. | ~6 líneas |
| **D7** | **JWT**: TTL **5 min** + grants mínimos (`canPublishSources:["microphone"]`, `canPublishData:false`, `canUpdateOwnMetadata:false`) + **`room`/`identity` los fija el server** | Doc oficial: el TTL **solo afecta el join**, no las reconexiones → **corto es seguro**. Self-hosted **no tiene revocación** → el TTL **es** la única red. | Params de la lib |

**Impacto en NFR1 (rendimiento — crucial)**: el hot path del turno de voz **no pasa por HTTP** salvo `POST /state` (una transición del orbe). El middleware agrega: un dict lookup (`Host`), un `compare_digest` sobre 43 chars, y un `int()` del `Content-Length`. **Orden de microsegundos.** El `/events` es una conexión long-lived: se autentica **una vez**. **Impacto medible esperado: cero.** Se verifica en Build & Test.

---

## Pasos

- [x] **Paso 1** — Analizar el contexto de la unidad (FR3, código de `orb_server.py`, `orb.html`, `vc/config.py`, `vcctl.py`, tests de U1).
- [x] **Paso 2** — Crear el plan (v1 → v2 → **v3**).
- [x] **Paso 3** — Preguntas de contexto → **resueltas**: v1 por investigación, v2 por decisión de proporcionalidad del usuario.
- [x] **Paso 3.5** — Investigación del estándar (fuera del framework, pedida por el usuario) → `ciclo9-security-research.md`.
- [x] **Paso 4** — Decisiones D1–D7 fijadas. **El usuario delegó al 100%** (*"TE LO ENCARGO AL 100%"*), con dos restricciones duras: **rendimiento crucial** + **seguridad proporcional a que es local**.
- [x] **Paso 5** — Generar artefactos en `construction/U2-orb-server/functional-design/`:
  - [x] `business-logic-model.md` — cadena de validación + **Testable Properties (PBT-01)**
  - [x] `business-rules.md` — reglas duras
  - [x] `domain-entities.md` — entidades
- [x] **Paso 6** — Presentar completitud del stage + compliance SECURITY/PBT.

---

## Propiedades testables (PBT-01) — se formalizan en `business-logic-model.md`

| # | Propiedad | Por qué property-based y no un ejemplo |
|---|---|---|
| **U2-P1** | ∀ ruta ≠ `/healthz`, ∀ request **sin token válido** → **nunca** 2xx | Deny-by-default es un invariante universal, no una lista de casos |
| **U2-P2** | ∀ `Host` ∉ allowlist exacta → **403** | Hypothesis **va a generar** `127.0.0.1.evil.com`, `127.0.0.1:8777.evil.com`… los bypasses de substring exactos |
| **U2-P3** | ∀ respuesta → **ningún** header `Access-Control-*` | Una regresión acá reabre S6 en silencio |
| **U2-P4** | ∀ body con `len > límite(ruta)` → **413** y **no se escribe nada** en disco | El oráculo es observable: el archivo **no existe** |
| **U2-P5** | ∀ JWT minteado → grants ⊆ mínimo, y `room`/`identity` == los del server **ignorando el query** | Round-trip: decodificar el JWT y verificar los claims |
| **U2-P6** | ∀ token candidato ≠ el real → rechazado (y la comparación es constant-time) | Cubre el charset entero, no 3 ejemplos |
