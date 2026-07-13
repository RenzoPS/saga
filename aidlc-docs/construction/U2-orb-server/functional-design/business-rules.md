# U2 — Business Rules: reglas duras de `orb_server`

**Unidad**: U2 · **FR3.1 … FR3.7**
Reglas **no negociables**. Cada una tiene: el enunciado, el porqué (el ataque que tapa o el bug que
evita), y **cómo se verifica**.

---

## BR-1 — Deny by default (SECURITY-08)
**Regla**: **ningún** endpoint responde 2xx sin token válido. **Excepciones: `/healthz` y `/vendor/*`.**

> **`/vendor/*` exento del token** (corregido en validación en vivo, 2026-07-13): three.js y el SDK de
> LiveKit se cargan por `<script src>` / `import` de ES modules, que **no pueden mandar el header
> `X-Orb-Token`** (misma limitación del browser que el SSE). Exigir token ahí dejaba la página **sin
> three.js → WebGL muerto** (síntoma: *"No cargó WebGL/Three.js"*). Son **assets estáticos sin
> secretos** → van públicos, que es el patrón del estándar ("mutaciones + secretos piden token; assets
> públicos"). **Siguen** detrás del `Host` check (BR-4) y del bloqueo de path traversal de `_serve_vendor`.

**Corolario estructural (el que importa)**: la validación vive en **una sola puerta**, ejecutada
**antes** de cualquier handler. **Prohibido** el check por-handler.
**Por qué**: hoy `_authorized()` se llama **solo en `do_POST`** → `/token` y `/events` quedan abiertos
*incluso con token configurado*. Una auth opt-in por ruta **garantiza** que el próximo endpoint nazca
inseguro.

**Verificación**: `U2-P1` (∀ ruta × ∀ método sin token → nunca 2xx).

---

## BR-2 — El token nunca puede estar vacío (cierra S5)
**Regla**: si `ORB_TOKEN` no viene en el env, el server **lo autogenera** (`secrets.token_urlsafe(32)`).
**Prohibido** el default `""`, y **prohibido** que "sin token" signifique "sin auth".

**Por qué**: `TOKEN = os.environ.get("ORB_TOKEN", "")` + `if not TOKEN: return True` (líneas 44 y
110-111) es **exactamente** el patrón de Ollama pre-0.1.29 (**CVE-2024-28224**).

**Verificación**: `U2-P1`, y el xfail-strict de U1 `test_no_auth_by_default_is_the_hole` → **XPASS**
(y hay que **des-marcarlo**).

---

## BR-3 — Comparación de secretos en tiempo constante
**Regla**: el token se compara con **`hmac.compare_digest`**. **Prohibido `==`.**
**Por qué**: `==` corta en el primer byte distinto → timing leak.

**Verificación**: `U2-P6` + grep de que no haya comparación directa del token.

---

## BR-4 — `Host`: allowlist exacta, y va PRIMERO (cierra S6)
**Regla**: `Host` ∈ `{"127.0.0.1:P", "localhost:P", "[::1]:P"}` — **igualdad exacta**.
**PROHIBIDO**: `in`, `startswith`, `endswith`, regex laxa.
**Orden**: es el **primer** check de la cadena, antes del token.

**Por qué**:
- `"127.0.0.1" in host` **deja pasar `127.0.0.1.evil.com`** — es el bypass que OWASP advierte explícito.
- Va primero porque bajo **DNS rebinding** el atacante **es same-origin**: el browser le manda el token
  igual. **Ninguna capa posterior lo detectaría.** Este check es **la** defensa (la que Ollama no tenía).

**Verificación**: `U2-P2` (Hypothesis genera los hosts adversariales).

---

## BR-5 — Cero CORS
**Regla**: el server **no emite NINGÚN** header `Access-Control-*`. Nunca. En ninguna respuesta.
**Por qué**: `Access-Control-Allow-Origin: *` (hoy, líneas 188 y 283) **invita** a cualquier página a
leer las respuestas — incluida la de `/token`, que **contiene el JWT**. Además, sin esta regla el
preflight que fuerza `X-Orb-Token` **no es una defensa**: es decoración.

**Verificación**: `U2-P3` (∀ respuesta → ningún header `Access-Control-*`).

---

## BR-6 — Límite ANTES de leer el body
**Regla**: si `Content-Length > límite(ruta)` → **413**, y el body **no se lee**.
**Prohibido** leer primero y validar después.
**Por qué**: `/attach` escribe a `/tmp`, que es **tmpfs = RAM**. Leer un body de 4 GB "para después
rechazarlo" **ya te comió la RAM**. Cortar antes = el ataque no toca ni RAM ni disco.

**Límites**: `/attach` **10 MB** · `/say`, `/stage` **64 KB** · resto de POST **8 KB**.
(Un PNG full-HD ronda 1–3 MB → 10 MB da margen 3×. 64 KB de texto ≈ 10.000 palabras: un prompt de voz
jamás llega ahí.)

**Verificación**: `U2-P4` — el oráculo es el filesystem: **el archivo no existe**.

---

## BR-7 — El cliente NO elige `room` ni `identity` (cierra S8)
**Regla**: `room` e `identity` los fija el **server**. El query del cliente se **ignora**.
**Por qué**: hoy salen del query **sin validar** y **se firman en el JWT** → el cliente elige en qué
room entra y con qué identidad.

**Verificación**: `U2-P5` (∀ query del cliente → el JWT lleva los del server).

---

## BR-8 — JWT: TTL explícito + grants mínimos
**Regla**: TTL **5 minutos**. Grants **exactamente**:
`room_join` · `room` (fijo) · `can_subscribe` · `can_publish` con `can_publish_sources=["microphone"]`
· `can_publish_data=False` · `can_update_own_metadata=False`.
**Prohibido**: `room_create`, `room_admin`, `room_record`, `ingress_admin`, y **heredar los defaults
del SDK**.

**Por qué el TTL corto es seguro** (doc oficial de LiveKit, textual):
> *"Expiration time only impacts the initial connection, and not subsequent reconnects."*

→ **No rompe reconexiones.** Y como **self-hosted no tiene revocación**, el TTL corto **es la única
red** si el JWT se filtra.

**Verificación**: `U2-P5` (decodificar el JWT: `exp - iat ≤ 5min`, grants ⊆ mínimo).

---

## BR-9 — Fail-closed (NFR4)
**Regla**: ante error, excepción o ambigüedad en **cualquier** paso de la puerta → **denegar**.
**Prohibido** el `try/except` que degrada a "permitir".
**Por qué**: es el bug **S2** del guard (fail-open), que este ciclo está corrigiendo. No se replica.

---

## BR-10 — La CSP no puede romper el WebRTC
**Regla**: la CSP se limita a `frame-ancestors 'none'; form-action 'none'; base-uri 'none'`.
**Prohibido** restringir `script-src` o `connect-src` **sin verificación empírica en vivo**.
**Por qué**: `connect-src` mal enumerado **rompe el WS de LiveKit → saga queda muda** (riesgo C1). El
beneficio (XSS en una página propia, local) **no justifica** el riesgo.
**Excepción documentada a SECURITY-04** — registrada en requirements §FR3-OUT.

---

## BR-11 — C1: el cambio cliente↔server es ATÓMICO
**Regla**: `orb_server` y `orb.html` se modifican **en el mismo commit**. **Prohibido** mergear el
server endurecido sin el cliente que manda el token.
**Por qué**: si el server exige token y el cliente no lo manda → **el orbe no conecta y saga queda
muda**. Es el riesgo #1 de la unidad.
**Verificación**: **validación en vivo obligatoria** (turno de voz completo) antes de cerrar U2.

---

## Reglas que NO existen (descartadas por proporcionalidad — ver requirements §FR3-OUT)
- ~~Rate limit en `/say`~~ → con token, el único que puede llamarlo **sos vos**.
- ~~Cookie de sesión~~ → 3 piezas nuevas + *cookie tossing* como problema nuevo; el `?token=` en
  `localhost` no tiene a quién filtrarse.
- ~~Validación de `Origin`~~ → con token + `Host` check + cero CORS + `form-action 'none'`, no frena
  ningún ataque nuevo.
- ~~`Sec-Fetch-Site`~~ → redundante: el token ya cubre el hueco de los GET/SSE.
