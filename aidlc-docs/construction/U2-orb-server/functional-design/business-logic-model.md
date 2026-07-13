# U2 — Business Logic Model: cadena de validación de `orb_server`

**Unidad**: U2 — Hardening de `orb_server` · **FR3.1 … FR3.7**
**Stage**: Functional Design (obligatorio por **PBT-01**)

---

## 1. El modelo en una frase

Hoy `orb_server` atiende **cualquier** request. El diseño introduce **una única puerta** —
`_gate()` — por la que pasan **todos** los requests **antes** de tocar cualquier handler. La puerta
es **fail-closed**: si algo no cierra, devuelve un error y **no ejecuta nada**.

**Por qué una sola puerta y no un check por handler**: hoy `_authorized()` se llama **solo en
`do_POST`** (línea 217) → `/token` y `/events` quedan abiertos **incluso si hay token configurado**.
Ese es exactamente el bug que produce una auth "opt-in por ruta": **un endpoint olvidado tira todo el
trabajo**. La puerta única lo hace estructuralmente imposible.

---

## 2. La cadena (orden estricto — el orden es parte del diseño)

```
request
   │
   ├─[1]─ ¿Host ∈ allowlist exacta?          NO → 403  (anti-DNS-rebinding, FR3.7)
   │        {127.0.0.1:P, localhost:P, [::1]:P}
   │        va PRIMERO: bajo rebinding el atacante es same-origin,
   │        así que ninguna capa posterior lo detectaría
   │
   ├─[2]─ ¿ruta == /healthz?                 SÍ → 200 "ok"  (única excepción; no expone nada)
   │
   ├─[3]─ ¿token válido?                     NO → 401  (deny-by-default, FR3.1)
   │        header X-Orb-Token   (los fetch)
   │        ?token=<t>           (bootstrap GET / y GET /events)
   │        comparación: hmac.compare_digest  (constant-time)
   │
   ├─[4]─ ¿Content-Length ≤ límite(ruta)?    NO → 413  (FR3.4)
   │        el body NO se lee: se corta ANTES de tocar RAM/disco
   │        /attach 10MB · /say,/stage 64KB · resto 8KB
   │
   └─→ handler  →  respuesta + headers de seguridad (FR3.3) + CERO headers CORS (FR3.2)
```

**Invariante de orden**: `[1]` antes que `[3]`. Un request de rebinding **trae** el token si el
browser lo tiene en la URL — por eso el `Host` check tiene que rechazarlo **antes** de que la validez
del token lo salve.

---

## 3. Flujo del token (ciclo de vida completo)

```
saga-ctl start
   │
   ├─ vcctl genera: ORB_TOKEN = secrets.token_urlsafe(32)      ← efímero, NO toca el disco
   │
   ├─ lanza orb_server con ORB_TOKEN en el env
   │
   └─ xdg-open  http://127.0.0.1:8777/?token=<t>
                                    │
                                    ▼
                          orb.html (browser)
                                    │
             ┌──────────────────────┼──────────────────────┐
             │                      │                      │
     lee el token de la URL   EventSource              fetch (POST /say,
     y lo guarda en memoria   /events?token=<t>        /stage, /attach, GET /token)
     history.replaceState()   (el query param NO es    header: X-Orb-Token: <t>
     → limpia la barra         una elección: SSE no    → fuerza el preflight CORS
                               acepta headers custom)
```

**Reinicio de saga** → token nuevo → una pestaña vieja recibe **401** (falla **ruidosa**, no
silenciosa). `saga-ctl` reabre el browser solo, así que en la práctica no se nota.

---

## 4. Reglas de decisión por endpoint

| Ruta | Método | Token | Límite body | Notas |
|---|---|---|---|---|
| `/healthz` | GET | **no** | — | Única excepción (probe de readiness de `vcctl`) |
| `/` `/index.html` | GET | **sí** (`?token=`) | — | Bootstrap. El HTML se sirve tal cual (sin nonce: ver §6) |
| `/vendor/*` | GET | **sí** (`?token=`) | — | Path traversal ya bloqueado (test verde de U1) |
| `/events` | GET | **sí** (`?token=`) | — | SSE. Se autentica **una vez** (conexión long-lived) → cero costo por evento |
| `/token` | GET | **sí** (header) | — | **Mintea el JWT** → `room`/`identity` los fija el SERVER (FR3.6) |
| `/state` | POST | **sí** (header) | 8 KB | Lo llama el agente en cada transición del orbe → el path más caliente |
| `/stage` | POST | **sí** (header) | 64 KB | |
| `/say` | POST | **sí** (header) | 64 KB | Dispara un turno LLM completo |
| `/attach` | POST | **sí** (header) | **10 MB** | Escribe a `/tmp` (**tmpfs = RAM**) → el límite es lo que evita llenar la RAM |

---

## 5. Minteo del JWT (FR3.5, FR3.6)

**Antes** (líneas 150-163): `identity` y `room` salen del **query del cliente** y se **firman en el
JWT**; grants = `room_join=True, room=room` **y nada más** (hereda los defaults del SDK); **sin TTL**
(default: 6h).

**Después**:
```
identity ← constante del server (no del query)
room     ← LIVEKIT_ROOM (constante del server, no del query)
ttl      ← 5 minutos          # solo tiene que cubrir el JOIN
grants   ← room_join ✓ · room (fijo) · can_subscribe ✓
           can_publish ✓ con can_publish_sources = ["microphone"]   # solo mic
           can_publish_data = False · can_update_own_metadata = False
           # cero room_create / room_admin / room_record / ingress_admin
```

**Fundamento del TTL (doc oficial de LiveKit, textual)**:
> *"Expiration time only impacts the initial connection, and not subsequent reconnects."*
> *"LiveKit server proactively issues refreshed tokens to connected clients."*

→ Un TTL corto **no rompe reconexiones** (el server empuja tokens refrescados por el signal channel).
→ El TTL **no limita** la duración de la sesión.
→ **Self-hosted no tiene revocación** (es Cloud-only) → **el TTL corto ES la única red** si el JWT se
filtra.

---

## 6. Decisión explícita: la CSP **no** restringe `script-src` ni `connect-src`

CSP adoptada: `frame-ancestors 'none'; form-action 'none'; base-uri 'none'`.

- **`form-action 'none'` es el control que gana**: mata el `POST` por `<form>` — **el único vector
  CSRF que el header custom NO puede frenar** (un `<form>` no puede setear headers, pero tampoco
  dispara preflight → llegaría igual).
- **Se descarta restringir `script-src`/`connect-src`**: obligaría a enumerar el WS de LiveKit y
  **rompería el WebRTC → saga queda muda** (el riesgo del punto C1), a cambio de defender contra XSS
  inyectado **en una página que servimos nosotros, con contenido que escribimos nosotros, en local**.
  **Excepción documentada a SECURITY-04** (requirements §FR3-OUT).

---

## 7. Testable Properties (PBT-01) — el entregable obligatorio de este stage

Las propiedades son **invariantes universales**, no ejemplos. Se implementan con **Hypothesis** (perfil
`thorough` para las de seguridad, como en U1).

| # | Propiedad | Generador | Oráculo | Cierra |
|---|---|---|---|---|
| **U2-P1** | ∀ ruta ≠ `/healthz`, ∀ request **sin token válido** → **nunca** 2xx | rutas × métodos × (sin token, token vacío, token basura, token con whitespace) | `status ∉ [200,299]` | **S5** |
| **U2-P2** | ∀ `Host` ∉ allowlist exacta → **403** | strings de host adversariales | `status == 403` | **S6** |
| **U2-P3** | ∀ respuesta de ∀ ruta → **ningún** header que empiece con `Access-Control-` | todas las rutas | `not any(h.lower().startswith("access-control-"))` | **S6** |
| **U2-P4** | ∀ body con `len > límite(ruta)` → **413** **y el archivo de destino no se creó** | `binary(min_size=límite+1)` | `status == 413` **y** `not ATTACH_IMG_PATH.exists()` | **S8** |
| **U2-P5** | ∀ `identity`/`room` que mande el cliente por query → el JWT emitido **los ignora** y lleva los del server, con grants ⊆ mínimo y `exp - iat ≤ 5min` | `text()` para identity/room | decodificar el JWT y comparar claims | **S8, S10** |
| **U2-P6** | ∀ token candidato ≠ el real → rechazado | `text()` sobre el charset completo | `status == 401` | **S5** |

**Por qué property-based y no ejemplos** (justificación de PBT-01):
- **U2-P2 es el caso testigo**: la trampa es el **match por substring**. Un test de ejemplo con
  `Host: evil.com` pasa con una implementación rota (`if "127.0.0.1" in host`). Hypothesis **genera**
  `127.0.0.1.evil.com` y `127.0.0.1:8777.evil.com` — y **encuentra el bypass**.
- **U2-P1 y U2-P3** son invariantes sobre el **producto cartesiano rutas × métodos**: enumerarlo a
  mano garantiza que el próximo endpoint que se agregue **quede sin cubrir**. La propiedad **no**.

**PBT-05 (oracle)**: aplica en **U2-P4** (el oráculo es el filesystem: el archivo **no existe**) y en
**U2-P5** (el oráculo es el JWT decodificado). No es N/A en esta unidad — a diferencia de U1.

---

## 8. Impacto en NFR1 (rendimiento — restricción dura del usuario)

El **hot path del turno de voz no pasa por este servidor**, salvo `POST /state` (una transición del
orbe). Lo que la puerta agrega, por request:

| Paso | Costo |
|---|---|
| `Host` check | un lookup en un `frozenset` |
| Token | un `hmac.compare_digest` sobre 43 chars |
| Límite | un `int()` sobre `Content-Length` |
| Headers | 4 `send_header()` |

**Orden de microsegundos.** `/events` es **long-lived**: se autentica **una vez**, no por evento.
**Impacto esperado: cero, no "bajo".** Se verifica en Build & Test contra el baseline de U1
(TTFT ~2.09s, modo rápido).
