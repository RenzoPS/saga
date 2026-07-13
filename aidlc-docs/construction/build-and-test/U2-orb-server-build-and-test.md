# U2 — Build & Test

**Unidad**: U2 — Hardening de `orb_server` · **Rama**: `feature/ciclo9-u2-orb-server`

## Estático — CERRADO OK

| Gate | Resultado |
|---|---|
| `py_compile` (5 archivos) | OK |
| import smoke (los 3 procesos: config, orb, vcctl, orb_server) | OK — `TOKEN` len 43 |
| `pytest tests/test_orb_server.py` | **15 passed** |
| `pytest` (suite completa) | **43 passed, 2 xfailed** (los 2 xfail = U3: S1, P7) |
| `pytest --thorough` (P1/P2/P6 a 1000) | **24 passed, 1 xfailed** |
| `ruff` | limpio |
| `mypy` (orb_server, config) | limpio |
| CORS residual en el server | **0 headers** (solo 2 comentarios que documentan la eliminación) |
| comparación insegura del token (`==`) | **0** (solo `hmac.compare_digest`) |
| `fetch` crudos sin token en `orb.html` | **0** (todos por `__orbFetch`) |

## Verificación funcional con `curl` (server real, puerto 8799)

| Caso | Esperado | Obtenido |
|---|---|---|
| `/healthz` sin token, host ok | 200 | ✅ 200 |
| `/` sin token | 401 | ✅ 401 |
| `/` con `?token=` válido | 200 | ✅ 200 |
| `/events` sin token | 401 | ✅ 401 |
| `/token` sin token (**era abierto**) | 401 | ✅ 401 |
| **Host rebinding con token válido** | 403 | ✅ 403 (el `Host` check gana) |
| `POST /say` sin token | 401 | ✅ 401 |
| `POST /say` con `X-Orb-Token` | 503 (no hay socket del agente en el test) | ✅ 503 |
| `POST /attach` con `Content-Length` > 10MB | 413 **sin leer el body** | ✅ 413 |
| headers | nosniff + XFO + Referrer + CSP, **sin CORS** | ✅ |

## NFR1 (rendimiento) — análisis + gate pendiente en vivo
El hot path del turno **no pasa por HTTP** salvo `POST /state`. La puerta agrega un lookup en
`frozenset` + un `compare_digest` (43 chars) + un `int()` → **microsegundos**. `/events` se autentica
**una vez** (long-lived). **Impacto esperado: cero.** Se confirma con el benchmark A/B contra el
baseline de U1 (TTFT ~2.09s) + la validación perceptual en vivo.

## Bug encontrado y corregido (valor del PBT)
**U2-P6**: `hmac.compare_digest` tira `TypeError` con strings no-ASCII → un token Unicode por `?token=`
**crasheaba el handler** (fail-open por excepción). Corregido a fail-closed (`try/except → False`).

## Validación EN VIVO (C1, riesgo #1) — CERRADA OK (2026-07-13)
El usuario levantó saga y validó el **turno de voz completo por las tres vías**: texto (Shift+Enter),
wake ("hey saga") y **Win+Z** — todas graban, procesan y responden por voz. Cambio atómico
server+cliente+agente confirmado en vivo.

### 4 bugs encontrados y corregidos DURANTE la validación en vivo (el valor del gate C1)
Ninguno lo agarraba la suite estática — son de integración real browser↔server↔desktop:
1. **`/vendor/*` pedía token** → three.js se carga por `import` de ES modules (sin headers) → WebGL
   muerto. Fix: `/vendor/*` exento (assets sin secretos), sigue tras el `Host` check.
2. **401 al refrescar** → `history.replaceState` limpiaba el token → un F5 re-pedía `/` sin token.
   Fix: dejar el token en la URL (local + `Referrer-Policy: no-referrer`).
3. **Desync del token** → `reset_orb_token()` corría en `start` con el server vivo → archivo con token
   nuevo, server con el viejo. Fix: rotar **solo** en `stop`.
4. **Nada procesaba** → `__orbFetch` definido **después** de un `await` en el módulo de three.js → el
   módulo de LiveKit lo llamaba `undefined` → `/token` fallaba → sin room. Fix: `__orbFetch` en un
   `<script>` plano antes de los módulos. **Verificado con browser real (Playwright)**: `token OK` →
   `room CONNECTED` → `TTS track attached`.

### NO-bug (registrado para no confundir): Win+Z
Win+Z **no** era de saga ni de U2. El código del path (emisor → socket → agente) se probó end-to-end y
anda. La causa era de **entorno**: el binding de Hyprland se había perdido en una update de los dots de
KooL (`hyprctl binds` mostró **cero** binds de Z). Repuesto en `~/.config/hypr/UserConfigs/UserKeybinds.conf`
(user-override, sobrevive updates) con la skill `kool-hyprland`.

## Verificación final (post-fixes en vivo)
`pytest` **45 passed, 2 xfailed** (los 2 = U3: S1, P7) · `thorough` **26 passed** · ruff **limpio** ·
mypy **limpio** · py_compile OK · diff = **solo los 7 archivos de U2** (cero producción fuera de scope).

## Deuda menor (no bloqueante, registrada)
`GET /favicon.ico` → 401 (el browser lo pide sin token). Cosmético, inofensivo. Se puede exentar como
`/vendor` en un pase futuro, o ignorar.
