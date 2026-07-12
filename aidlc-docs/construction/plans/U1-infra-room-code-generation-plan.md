# U1 — Infra room · Code Generation Plan (Ciclo 4)

> **Fuente única de verdad para Code Generation de U1.** Plan ejecutable paso a paso.
> Brownfield: "generar" = modificar archivos existentes cuando aplica, no duplicar.
> CONSTRUCTION Ciclo 4. Unidad U1 (sin dependencias; es la base de todas las demás).

## Contexto de la unidad
- **Qué entrega U1**: el transporte room operativo a nivel infraestructura — `livekit-server` corriendo
  local (Docker) + las credenciales en `.env.local` + el endpoint `/token` (en `orb_server`) que emite el
  JWT con el que el cliente (U3) se une al room. Sin esto, ni worker (U2) ni cliente (U3) pueden conectarse.
- **NO entrega**: el worker en modo room (U2), el cliente browser (U3), wake (U4), orbe sync (U5), saga-ctl (U6).
- **Dependencias**: ninguna (raíz del grafo). La habilitan: U2 (worker se conecta al server), U3 (cliente
  pide token + se une), U6 (saga-ctl la levanta).
- **Diseño de referencia**: `application-design/services.md` (orden de readiness), `component-dependency.md`
  (topología + `token-service depende de API_SECRET`), `unit-of-work.md` (U1).

## Constraints duros (de Requirements / decisiones del ciclo)
- **Local-only / privacidad**: el server bindea SOLO a `127.0.0.1` (loopback). Nada expuesto a la LAN.
- **Sin hardcodear versiones**: la imagen Docker de `livekit-server` se referencia por su tag estable
  vigente verificado al generar (no pinear de memoria una versión vieja).
- **Secretos**: `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` van a `.env.local` (gitignored). El plan NO imprime
  su contenido. La escritura de claves en `.env.local` la hace el usuario o un comando que no las vuelque a logs.
- **Fallback console**: U1 NO rompe el modo console actual. Es aditivo (nuevos archivos + endpoint nuevo).
- **NFR latencia**: server local = WebRTC loopback (~ms). El gate de latencia 2-3s se valida en Build&Test (post-U2/U3).

## Decisiones técnicas de U1
1. **Server**: `livekit-server` vía `docker-compose.yml` en el root. Config en `livekit.yaml` (dev keys,
   puerto 7880 ws, bind loopback). Modo dev/single-node (sin Redis; suficiente para 1 room local).
2. **Token endpoint**: `GET /token?identity=<id>&room=<room>` en `orb/orb_server.py`. Devuelve
   `{"url": "ws://127.0.0.1:7880", "token": "<jwt>"}`. El JWT se mintea con `livekit.api.AccessToken`
   + `VideoGrants(room_join=True, room=<room>)`, firmado con `LIVEKIT_API_SECRET`. Import lazy dentro del
   handler (mantiene el resto de `orb_server` stdlib-only; el venv ya tiene `livekit-api` por `livekit-agents`).
3. **Config**: `vc/config.py` expone `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `LIVEKIT_ROOM`
   (defaults razonables + override por env). Una sola fuente para worker (U2) y token endpoint.
4. **Keys**: generadas una vez (`livekit-server generate-keys` o equivalente) → a `.env.local`. Sin pinear.

## Archivos afectados (paths exactos — nunca en aidlc-docs/)
| Archivo | Acción | Detalle |
|---|---|---|
| `docker-compose.yml` | NEW | servicio `livekit-server`, bind `127.0.0.1:7880`, monta `livekit.yaml`, tag verificado |
| `livekit.yaml` | NEW | config del server: puerto, keys (ref a env), single-node dev |
| `vc/config.py` | MOD | constantes `LIVEKIT_URL/API_KEY/API_SECRET/ROOM` (lectura de env + defaults) |
| `orb/orb_server.py` | MOD | endpoint `GET /token` (mint JWT lazy import) + docstring actualizado |
| `.env.local` | MOD | `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `LIVEKIT_ROOM` (lo hace el usuario; secreto) |
| `pyproject.toml` | MOD (si hace falta) | `livekit-api` explícito SOLO si no es importable transitivamente |
| `.gitignore` | verificar | `.env.local` ya ignorado; `livekit.yaml` no lleva secretos (usa env) → versionable |

---

# PART 1 — PLANNING (este documento)

- [x] Step 1: Analizar contexto de U1 (diseño + dependencias + constraints)
- [x] Step 2: Plan detallado con archivos exactos y decisiones técnicas
- [x] Step 3: Contexto de generación (dependencias, interfaces: `ws://127.0.0.1:7880`, `/token`)
- [x] Step 4: Guardar este plan
- [x] Step 5: Resumir el plan al usuario
- [x] Step 6: Log del prompt de aprobación en audit.md
- [x] Step 7: Esperar aprobación explícita del usuario → aprobado (constraint: tag Docker = última versión específica)
- [x] Step 8: Registrar respuesta de aprobación en audit.md
- [x] Step 9: Marcar Part 1 completo en aidlc-state.md

---

# PART 2 — GENERATION (ejecutar tras aprobación)

> Cada paso se marca [x] al completarlo, en la MISMA interacción. Verificación proporcional al final.

- [x] **Step 10**: Generar config del server
  - [x] `livekit.yaml` — puerto 7880, keys vía env (`LIVEKIT_KEYS`), single-node, bind `127.0.0.1`
  - [x] `docker-compose.yml` — servicio livekit-server, tag **v1.13.1** (última específica verificada), host net + bind loopback, monta yaml
- [x] **Step 11**: Generar credenciales
  - [x] API key/secret generados (python `secrets`) y escritos a `.env.local` SIN imprimir el secreto + chmod 600
  - [x] `LIVEKIT_URL=ws://127.0.0.1:7880`, `LIVEKIT_ROOM=saga`
- [x] **Step 12**: Config Python (`vc/config.py`)
  - [x] Constantes `LIVEKIT_URL/API_KEY/API_SECRET/ROOM` + carga de `.env.local` al importar (single-source)
- [x] **Step 13**: Endpoint `/token` (`orb/orb_server.py`)
  - [x] `GET /token` en `do_GET`: parse `identity`/`room`, mint JWT (`livekit.api.AccessToken`, import lazy)
  - [x] Respuesta JSON `{url, token, room}`; error 500 si faltan keys o falla el mint
  - [x] Docstring del módulo actualizado (sumado `/token`)
- [x] **Step 14**: Deps (`pyproject.toml`)
  - [x] `from livekit import api` importable en el venv (vía livekit-agents) → no hizo falta agregar nada
- [~] **Step 15**: Verificación (proporcional — sin runtime de audio)
  - [x] `docker compose --env-file .env.local config -q` válido
  - [x] `.venv/bin/python -m py_compile orb/orb_server.py vc/config.py`
  - [x] `config` expone `LIVEKIT_*` (KEY/SECRET seteadas, sin imprimir)
  - [x] Mint + verify round-trip del JWT (identity/room/room_join correctos)
  - [x] **Server booteado y verificado (2026-06-23, Docker arriba)**: `docker compose --env-file .env.local up -d` → v1.13.1, bind 127.0.0.1, HTTP 200. Auth contra la room API OK (keys del container = .env.local). `/token` end-to-end vía orb_server → JSON válido.
  - [x] Modo console intacto (U1 es aditivo; no toca el runtime de audio actual)
- [x] **Step 16**: Resumen de código en `aidlc-docs/construction/U1-infra-room/code/generation-summary.md`
- [x] **Step 17**: Actualizar checkboxes + aidlc-state.md (U1 código generado; boot del server pendiente de daemon)

## Verificación / criterio de "U1 hecho"
- `docker compose up -d livekit-server` levanta el server bindeado a loopback.
- `curl http://127.0.0.1:7880/` responde (server vivo).
- `GET http://127.0.0.1:8777/token?identity=test&room=saga` devuelve `{url, token}` con JWT válido.
- `py_compile` OK en los archivos Python tocados. Modo console no regresiona.
- **Lo que NO se valida en U1**: el flujo de voz end-to-end (necesita U2+U3). Eso es Build&Test del ciclo.

## Story traceability
- Ciclo 4 es refactor de infra (User Stories = SKIP). Trazabilidad = `unit-of-work.md` U1 + `services.md`
  (orden de readiness, pieza #1 `livekit-server`).
