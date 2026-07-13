# Ciclo 9 — Investigación del estándar de industria (input de Requirements)

**Fecha**: 2026-07-13
**Disparador**: pedido explícito del usuario — *"antes de proseguir, investigá el estándar de seguridad para una IA agéntica por voz, cuáles son los patrones MÁS UTILIZADOS. No quiero que codeemos cosas [inventadas]; seguramente en la industria ya haya un estándar."*
**Método**: investigación web sobre fuentes primarias (OWASP, WHATWG Fetch, MDN, docs oficiales de LiveKit/Jupyter/Ollama/Syncthing/Anthropic/OpenAI, advisories de NCC Group y GitHub Security Lab).
**Estado**: es un **input** de Requirements, no un artefacto de diseño. Las decisiones que deriva viven en los requirements y en el plan de Functional Design de U2.

> **Honestidad intelectual (registrado tal como lo devolvió la investigación)**: **no existe una norma formal** (RFC/W3C) que diga "así se asegura un servidor local". Lo que llamamos "el estándar" es un **consenso de prácticas convergentes** (OWASP + NCC + Jupyter + Chrome + LiveKit + Anthropic). No se debe citar como si fuera normativo.

---

## 1. El modelo de amenaza real de un server en localhost

### 1.1 `localhost` NO es un límite de seguridad
- **Frente a otras páginas web**: la Same-Origin Policy **no impide enviar** requests a `http://127.0.0.1:8777`; solo impide *leer la respuesta*. Un `<form method=POST>` o un `fetch(..., {mode:'no-cors'})` desde cualquier pestaña abierta **llega igual**, y el efecto lateral ya ocurrió. MDN lo dice explícito: las *simple requests* existen porque el `<form>` de HTML 4.0 ya podía postear cross-origin, *"so anyone writing a server must already be protecting against CSRF"*.
- **Frente a otros procesos**: cualquier proceso del usuario puede hacer TCP a `127.0.0.1`. El bind a loopback protege de la red, **no de la máquina**.
- **Frente a extensiones del browser**: una extensión con `host_permissions` sobre `http://127.0.0.1/*` habla directo con el server.
- **Cookies sin scope de puerto**: una cookie para el host `127.0.0.1` es visible/seteable por **cualquier otro server local en cualquier otro puerto** → *cookie tossing* (precedente real: RCE en Google Cloud Jupyter Notebooks). **Corolario de diseño: la cookie NO puede ser la única credencial.**

### 1.2 DNS rebinding — la amenaza que rompe las defensas basadas en Origin/CORS
El atacante sirve JS desde `evil.com` con TTL de DNS ≈ 0 y luego re-resuelve `evil.com` → `127.0.0.1`. El browser ahora cree que `http://evil.com:8777/` es **same-origin**:
- No hay preflight, no hay CORS, y **el chequeo de `Origin` no sirve** (el `Origin` *es* `evil.com`, y coincide con el de la página).
- El atacante **lee las respuestas** → un endpoint que mintea JWTs se vuelve un dispensador de credenciales.

**Precedente exacto de saga**: **Ollama, [CVE-2024-28224](https://www.nccgroup.com/research-blog/technical-advisory-ollama-dns-rebinding-attack-cve-2024-28224/)** — servidor local de LLM sin auth; NCC Group demostró **exfiltración de archivos arbitrarios** vía rebinding. Es, literalmente, el estado actual de `orb_server`.

Recomendación textual de NCC Group:
> *"DNS rebinding attacks can also be prevented by **validating the `Host` HTTP header** on the server-side to only allow a set of authorized values. For services listening on the loopback interface, this set of whitelisted host values should only contain `localhost`, and all reserved numeric addresses for the loopback interface, including `127.0.0.1`."*

**Punto clave**: bajo rebinding el browser **no manda las cookies** del server local (cree estar en `evil.com`). Por eso lo que mata el vector es: **un secreto que el atacante no puede adivinar (token) + validación de `Host`**. El chequeo de `Origin`, solo, **no alcanza**.

### 1.3 Lo que viene y NO nos salva hoy
Chrome está lanzando **Local Network Access** (prompt de permiso para requests *public → loopback*). Cubre exactamente este vector, pero: (1) solo Chrome, (2) no cubre páginas servidas desde otro origen local. **No es una defensa que se pueda asumir.**

---

## 2. Qué hace cada producto maduro (la evidencia)

| Producto | Token secreto | Cookie | Header custom | Origin check | **Host check** |
|---|---|---|---|---|---|
| **Jupyter Server** | ✅ token aleatorio (`Authorization`, `?token=`, o form de login) | ✅ sesión + `_xsrf` | ✅ `X-XSRFToken` (double-submit) | ✅ `allow_origin` (default: same-origin) | ✅ **sí** — `allow_remote_access=False` + `local_hostnames`; **403 si el `Host` dice que el browser cree estar en un dominio no-local**, textualmente *"to protect against DNS rebinding"* |
| **Syncthing** | ✅ API key (`X-API-Key`) | ✅ cookie CSRF seteada al servir `/` | ✅ token CSRF en header, obligatorio en **todas** las `/rest/`; sin él → 403 | — | (no verificado) |
| **qBittorrent WebUI** | ✅ API key (≥5.2) | ✅ `SID` post-login | — | ✅ exige `Referer`/`Origin` == `Host` | ✅ implícito |
| **VS Code Server** | ✅ connection token, **obligatorio** salvo `--without-connection-token`; viaja como `?tkn=` | (probable) | — | — | — |
| **Ollama** | ❌ **sin auth por diseño** | ❌ | ❌ | ✅ `OLLAMA_ORIGINS` | ✅ solo **desde v0.1.29** (fix del CVE) | 

**Conclusión**: el patrón maduro es **multicapa**. Nadie serio depende de un solo mecanismo. Ollama es el ejemplo de **qué no hacer** — y es el que más se parece a saga hoy.

---

## 3. El patrón destilado (lo que la industria realmente hace)

Middleware único, **fail-closed**, antes de cualquier handler:

1. **Bind a `127.0.0.1`** — necesario, **no** suficiente.
2. **Token**: `secrets.token_urlsafe(32)` generado al arrancar, en memoria. Comparación con **`hmac.compare_digest`** (constant-time; `==` es un timing leak).
3. **Host check (anti-rebinding, PRIMERO de todo)**: `Host` ∈ `{127.0.0.1:P, localhost:P, [::1]:P}` — **match exacto**. Nada de `startswith`/`in` (`"127.0.0.1" in host` deja pasar `127.0.0.1.evil.com`; OWASP lo advierte explícito).
4. **Auth en TODO endpoint** (incluidos el SSE y el HTML), por cualquiera de estas vías:
   - header `X-Orb-Token` (clientes `fetch`) → **fuerza el preflight CORS**;
   - cookie `HttpOnly; SameSite=Strict` (para `EventSource`, que no acepta headers);
   - `?token=` **solo** en el bootstrap `GET /` → el server setea la cookie y **redirige a URL limpia** (flujo Jupyter).
5. **Origin check** en métodos que mutan estado: presente y **exactamente igual**; ausente o distinto → 403. OWASP: *"If neither of these headers are present... **We recommend blocking**."*
6. **`Sec-Fetch-Site`**: cubre el hueco de GET/SSE, donde `Origin` **no viene** en same-origin. Los browsers lo mandan siempre. Regla: ausente → permitir (cliente no-browser: ya lo frena el token); presente y ∉ `{same-origin, none}` → 403.
7. **NO emitir NINGÚN header `Access-Control-*`.** Esto es lo que hace que el preflight del punto 4 sea una defensa real. `Access-Control-Allow-Origin: *` (o reflejar el `Origin`) **anula todo lo anterior** — es el bug #1 que reporta GitHub Security Lab.
8. **Rate limit + límite de concurrencia** en el endpoint caro.
9. **Headers de seguridad** en todas las respuestas (§5).

### Por qué ninguna capa es redundante (esto es lo que justifica el diseño)
| Atacante | Lo frena |
|---|---|
| Página web común (CSRF) | Origin + `Sec-Fetch-Site` + preflight (no-CORS) **y** el token (no lo conoce) |
| **DNS rebinding** | **Host check** + **token** (Origin/CORS **NO** lo frenan: es same-origin) |
| Proceso local malicioso | **Solo el token** (puede falsificar cualquier header). Límite real = permisos del filesystem |

### El mecanismo del header custom (por qué es defensa CSRF válida — OWASP lo endorsa)
`X-Orb-Token` **no** está en la CORS-safelist → el request deja de ser *simple* → el browser **debe** mandar un preflight `OPTIONS` → el server no responde `Access-Control-Allow-*` → **el browser nunca envía el request real**. Y un `<form>` HTML **no puede setear headers**, así que la vía "simple request" también queda cerrada.

⚠️ **Caveat**: el header **de presencia** (vacío, tipo `X-Orb: 1`) frena CSRF web pero es **inútil** contra rebinding (ahí el atacante es same-origin y puede setearlo) y contra procesos locales. **Si se exige un header, tiene que llevar el secreto.**

---

## 4. Voice AI / agentes — el estándar (LiveKit, OpenAI, Anthropic, OWASP)

### 4.1 Token efímero acuñado server-side (consenso universal)
El cliente **nunca** tiene una API key; tiene un token efímero que emite el backend. OpenAI Realtime: ephemeral client secret que **expira en ~1 minuto**; textual: *"Never expose your standard OpenAI API key to a browser or a client device."* Vapi: JWT con `expiresIn`. LiveKit: JWT con grants.
→ En saga esto **ya se cumple**: Deepgram/Anthropic/TTS jamás se hablan desde el browser (viven en el agent worker). El browser solo publica el mic.

### 4.2 TTL del JWT de LiveKit — **corrige un supuesto falso del plan de U2**
Doc **oficial** de LiveKit, textual:
> **"Expiration time only impacts the initial connection, and not subsequent reconnects."**
> **"LiveKit server proactively issues refreshed tokens to connected clients"** … *"Refreshed tokens expire after 10 minutes or the remaining lifetime of the original token, whichever is longer."*

Consecuencias **duras** para el diseño:
- Un token expirado **NO** tira una sesión ya conectada.
- El SDK del browser **no reusa el token viejo ni refetchea el backend** en la reconexión: usa el token **refrescado** que el server le fue empujando por el signal channel.
- → **El riesgo que el plan de U2 anotó en Q7 ("que el SDK reuse un token viejo al reconectar") NO EXISTE.** Un TTL corto es seguro.
- → Y al revés: **el TTL NO sirve como límite de duración de sesión.** Cortar sesiones requiere `RemoveParticipant` vía admin API.
- **Self-hosted no tiene revocación** (es LiveKit Cloud only) → el TTL corto **es** la única red.
- El *"TTL de 15 minutos"* que circula en blogs **NO es guidance oficial**. El default documentado es 6h (el SDK Ruby usa 4h — hay discrepancia doc/código). Lo correcto es **setearlo explícito**.

### 4.3 Grants mínimos (least privilege) — **gap no cubierto por los requirements originales**
Hoy saga mintea `VideoGrants(room_join=True, room=room)` y **nada más** → hereda los defaults del SDK. Lo correcto:
```
roomJoin: true · room: "<fijo, del server>" · canSubscribe: true
canPublish: true · canPublishSources: ["microphone"]   # solo mic: ni cámara ni screenshare
canPublishData: false · canUpdateOwnMetadata: false
# nada de roomCreate / roomAdmin / roomRecord / ingressAdmin
```
Además: **`identity` y `room` derivados del server, nunca del query del cliente** (hoy vienen del query sin validar y se firman en el JWT).

### 4.4 Prompt injection por voz (aplica a U3, se registra acá)
- El vector que **de verdad** pega en un pipeline STT→texto→LLM (como saga) **no** es el audio adversarial exótico: es el **trivial** — la tele, un podcast, otra persona. Cualquier voz en la sala se transcribe y entra al LLM como si fuera intención del usuario.
- Mitigación de mejor ratio costo/beneficio: **wake word / push-to-talk** (saga ya lo tiene).
- **Trust-tiering**: el transcript es **dato, nunca instrucción**. Nunca en el system prompt.
- ⚠️ **Gotcha crítico**: si la confirmación de una acción destructiva se da **por voz** ("¿confirmás? — sí"), es **inyectable por el mismo canal del ataque**. La confirmación de lo irreversible tiene que salir del canal de voz (click/tecla). **Esto contradice la nota de §4.2 de los requirements** ("la confirmación *es* la conversación") → hay que revisarla en U3.
- La investigación (Interspeech 2025) es explícita: adversarial training ayuda pero **no elimina** la vulnerabilidad. **La defensa que carga peso no está en la capa de audio: está en la capa de autorización de tools.**

### 4.5 OWASP — versiones vigentes (números reales, no de memoria)
**OWASP Top 10 for LLM Applications v2025**: aplican **LLM01 Prompt Injection** (riesgo #1), **LLM06 Excessive Agency** (#2), **LLM05 Improper Output Handling**, **LLM02 Sensitive Information Disclosure**, **LLM10 Unbounded Consumption**.

**OWASP Top 10 for Agentic Applications 2026** (ASI01–ASI10, publicado 2025-12-09): aplican **ASI01 Agent Goal Hijack**, **ASI02 Tool Misuse & Exploitation**, **ASI03 Agent Identity & Privilege Abuse**, **ASI05 Unexpected Code Execution**, **ASI06 Memory & Context Poisoning**, **ASI09 Human-Agent Trust Exploitation**.
> ⚠️ *Verificación parcial*: los nombres ASI01–ASI10 se tomaron de fuentes secundarias coincidentes (el detalle vive en un PDF que no se leyó directo). Tres confirmados desde el anuncio oficial: *Agent Behavior Hijacking, Tool Misuse and Exploitation, Identity and Privilege Abuse*.

### 4.6 Anthropic / OpenAI — guidance de agentes con tools (input directo para U3)
De *"How we contain Claude across products"* (Anthropic):
- Orden de prioridad, textual: **"Design for containment at the environment layer first, then steer behavior at the model layer."** Las defensas del modelo son **probabilísticas y no compensan un boundary débil**.
- **Dato que rompe el mito del HITL**: ~**93% de los permission prompts se aprueban sin leerlos** — y cuantos más prompts ve el usuario, **menos** atención les presta. (Es **ASI09** medido en producción.) → **Si confirmás todo, no confirmás nada.** La confirmación debe ser **rara, específica y con readback**.
- **Allowlists = capability grants, no filtros de destino** (tuvieron exfiltración *a través de un dominio aprobado*).
- Claude Code: **sandbox a nivel OS** (Seatbelt/bubblewrap) + aprobación humana para ops sensibles.

**Consenso HITL**: nadie defiende autonomía plena con tools destructivas. El patrón canónico es **propose → commit**: *"The AI never executes high-risk actions directly. It proposes them, and a human commits them."*

---

## 5. Headers de seguridad — baseline (OWASP)

| Header | Valor | Por qué |
|---|---|---|
| `Content-Security-Policy` | `default-src 'none'; script-src 'nonce-<n>'; style-src 'nonce-<n>'; img-src 'self' data: blob:; connect-src 'self' <ws del livekit>; media-src 'self' blob:; frame-ancestors 'none'; form-action 'none'; base-uri 'none'` | `form-action 'none'` **mata el POST-por-form** (vector CSRF clásico). ⚠️ `connect-src` **debe** enumerar el WS de LiveKit o rompe el WebRTC. |
| `X-Content-Type-Options` | `nosniff` | Baseline absoluto. |
| `X-Frame-Options` | `DENY` | Backstop legacy de `frame-ancestors`. |
| `Referrer-Policy` | `no-referrer` | **Crítico si el token viaja por `?token=`**: evita fugarlo en el `Referer`. |
| `Cross-Origin-Resource-Policy` | `same-origin` | Barato; corta XS-leaks. |
| `Cross-Origin-Opener-Policy` | `same-origin` | Aísla el browsing context. |
| `Cache-Control` | `no-store` en todo lo que lleve token/JWT | Que el JWT no quede en el disk cache. |
| `Cross-Origin-Embedder-Policy` | **omitir** | `require-corp` rompe recursos cross-origin. No hace falta para WebRTC/`getUserMedia`. |
| `Strict-Transport-Security` | **no** | HTTP sobre loopback; `localhost` ya es *secure context*. |

---

## 6. Anti-patrones (lo que NO hay que hacer)

1. **"Es localhost, no hace falta auth."** → es Ollama pre-0.1.29 = CVE-2024-28224. **Es el estado actual de saga.**
2. **`Access-Control-Allow-Origin: *`** o reflejar el `Origin` → anula el preflight como defensa. **saga hace esto hoy** (`_ok204()` y `/events`).
3. **Chequear `Host`/`Origin` con substring** → `"127.0.0.1" in host` deja pasar `127.0.0.1.evil.com`.
4. **Solo `Origin`, sin token** → no sobrevive rebinding, ni un proceso local, ni los GET/SSE (donde `Origin` no viene).
5. **Solo cookie** → cookie tossing (las cookies no tienen scope de puerto).
6. **Dejar el `?token=` en la barra de direcciones** → historial, logs, `Referer`.
7. **Comparar el token con `==`** → timing attack. `hmac.compare_digest`.
8. **Auth opt-in por ruta** → un endpoint olvidado tira todo el trabajo. El middleware va **antes** de todo.
9. **Hardening por prompt como defensa primaria** → demostrablemente permeable (Anthropic: *"the model layer couldn't help"*).
10. **HITL como checkbox** → 93% de aprobación ciega.

---

## 7. Qué NO se pudo verificar (registrado explícitamente)
- Nombres ASI01–ASI10 desde el **PDF oficial** de OWASP (se usaron secundarias coincidentes).
- Docs de seguridad oficiales de **Deepgram, Retell AI y Pipecat** (las búsquedas devolvieron blogs de terceros).
- Si existe un **`maxDuration`** nativo en LiveKit (evidencia indirecta: un feature request abierto sugiere que **no**).
- Enforcement exacto del `Host` check en **Syncthing** y **qBittorrent** (no se leyó el source).
- **Los orígenes exactos que necesita `connect-src`** para el SDK de LiveKit (WS del server local, ICE/TURN). **Hay que enumerarlos empíricamente o la CSP rompe el WebRTC** → riesgo a verificar en vivo en U2.

---

## 8. Fuentes
**Amenazas / estándares**
- OWASP CSRF Prevention Cheat Sheet · OWASP HTTP Security Headers Cheat Sheet · OWASP CSP Cheat Sheet
- NCC Group — *Technical Advisory: Ollama DNS Rebinding Attack (CVE-2024-28224)*
- GitHub Security Lab — *Localhost dangers: CORS and DNS rebinding*
- MDN — CORS (simple requests / preflight), `Origin`, `EventSource` · WHATWG Fetch Standard (CORS-safelisted request-headers)
- web.dev — *Protect your resources with Fetch Metadata* (`Sec-Fetch-Site`)
- Chrome for Developers — *Local Network Access*
- s1r1us — *Cookie Tossing to RCE on Google Cloud Jupyter Notebooks*

**Productos**
- Jupyter Server — *Security* + *full-config* (`allow_remote_access`, `local_hostnames`) · Syncthing REST API + `lib/api/api_csrf.go` · qBittorrent WebUI API · Ollama FAQ (`OLLAMA_ORIGINS`) · VS Code Server

**Voice / agentes**
- LiveKit — *Generating tokens*, *Token grants*, *Security overview*, *Human-in-the-loop voice agents*, *Observer pattern guardrails*
- OWASP GenAI — *Top 10 for LLM Applications v2025* · *Top 10 for Agentic Applications 2026*
- Anthropic — *How we contain Claude across products* · OpenAI — *Agent Builder safety*, *Guardrails & approvals*, *Realtime (ephemeral keys)*
- NIST AI 600-1 (GenAI Profile) · CSA MAESTRO
- Repello — *Prompt injection attacks in Voice AI* (STT adversarial: Whisper/Wav2Vec2) · AudioJailbreak (CCS 2025) · Interspeech 2025 (defensas parciales)
