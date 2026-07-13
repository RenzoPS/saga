# U2 — Domain Entities

**Unidad**: U2 — Hardening de `orb_server`

Las entidades de esta unidad son **conceptuales**: no hay ORM ni base de datos. Se documentan porque
definen **qué se valida, con qué reglas y con qué ciclo de vida** — que es lo que después testea el PBT.

---

## E1 — Token del orbe (`OrbToken`)

| Atributo | Valor |
|---|---|
| **Qué es** | El secreto compartido entre `vcctl` (lo genera), `orb_server` (lo valida) y `orb.html` (lo presenta) |
| **Forma** | `secrets.token_urlsafe(32)` → 43 chars URL-safe |
| **Origen** | `vcctl` en cada `saga-ctl start`. **Autogenerado por el server** si el env no lo trae (BR-2) |
| **Persistencia** | **Ninguna.** Vive en el env del proceso y en la memoria del JS del browser |
| **Ciclo de vida** | Nace con `saga-ctl start`, muere con el proceso. Reinicio → token nuevo → la pestaña vieja da **401** |
| **Transporte** | `?token=` (bootstrap `GET /`, `GET /events`) · header `X-Orb-Token` (los `fetch`) |
| **Comparación** | `hmac.compare_digest` — **nunca `==`** (BR-3) |
| **Invariante** | **Nunca vacío.** Vacío ≠ "sin auth" (BR-2) |

**Por qué dos transportes**: no es una elección de diseño — **`EventSource` no acepta headers custom**
(restricción del browser, documentada en MDN). El query param es la **única** vía para el SSE.

---

## E2 — Petición HTTP entrante (`Request`)

Lo que la puerta (`_gate()`) inspecciona, **en este orden**:

| Campo | Regla | Falla → |
|---|---|---|
| `Host` | ∈ allowlist **exacta** `{127.0.0.1:P, localhost:P, [::1]:P}` (BR-4) | **403** |
| ruta | `/healthz` → única exenta de token | — |
| token | header `X-Orb-Token` **o** `?token=` → `compare_digest` (BR-1, BR-3) | **401** |
| `Content-Length` | ≤ `límite(ruta)` — **se valida ANTES de leer el body** (BR-6) | **413** |

**Límites por ruta**: `/attach` **10 MB** · `/say`, `/stage` **64 KB** · resto de POST **8 KB**.

**Invariante de orden**: `Host` **antes** que token. Bajo DNS rebinding el atacante **es same-origin**
→ el browser le manda el token igual → **solo el `Host` check lo detecta**.

---

## E3 — Grant de LiveKit (`AccessToken` / JWT)

Lo que `/token` mintea. **Todos** sus campos los fija el **server** (BR-7).

| Claim | Valor | Antes (bug) |
|---|---|---|
| `identity` | constante del server | **del query del cliente** (S8) |
| `room` | `LIVEKIT_ROOM` (constante del server) | **del query del cliente** (S8) |
| `exp - iat` (TTL) | **5 minutos** | **sin setear** → default del SDK: **6h** (S10) |
| `room_join` | ✓ | ✓ |
| `can_subscribe` | ✓ | (default del SDK) |
| `can_publish` | ✓, con `can_publish_sources = ["microphone"]` | (default del SDK: **todo**) |
| `can_publish_data` | **false** | (default del SDK) |
| `can_update_own_metadata` | **false** | (default del SDK) |
| `room_create` / `room_admin` / `room_record` / `ingress_admin` | **ausentes** | (defaults del SDK) |

**Ciclo de vida**: se mintea a demanda (el cliente lo pide en cada conexión). **El TTL solo gobierna
el `join`** — una vez conectado, el LiveKit server empuja **tokens refrescados** por el signal
channel, así que un TTL corto **no rompe reconexiones** (doc oficial).

**Nota de seguridad**: en **self-hosted no hay revocación** (es Cloud-only) → **el TTL corto es la
única red** si el JWT se filtra. Por eso el `Host` check importa tanto: bajo rebinding, un atacante
**lee** la respuesta de `/token` y **se lleva el JWT**.

---

## E4 — Respuesta HTTP saliente (`Response`)

| Header | Valor | Regla |
|---|---|---|
| `X-Content-Type-Options` | `nosniff` | BR — siempre |
| `X-Frame-Options` | `DENY` | BR — siempre |
| `Referrer-Policy` | `no-referrer` | BR — siempre (evita fugar el `?token=` por el `Referer`) |
| `Content-Security-Policy` | `frame-ancestors 'none'; form-action 'none'; base-uri 'none'` | BR-10 — **no** toca `script-src`/`connect-src` |
| `Cache-Control` | `no-store` | Ya existe; se mantiene (el JWT no va al disk cache) |
| **`Access-Control-*`** | **NINGUNO — jamás** | **BR-5** (hoy manda `*` en 2 lugares) |

---

## Entidades que NO existen (descartadas — ver requirements §FR3-OUT)

- ~~**Ventana de rate limit**~~ (deque de timestamps): descartada. Con token obligatorio, el único que
  puede llamar a `/say` **es el usuario**. Sería protegerlo de sí mismo.
- ~~**Cookie de sesión**~~: descartada. Traería *cookie tossing* (las cookies no tienen scope de
  puerto) como problema **nuevo**, a cambio de esconder el token de una URL **local**.
