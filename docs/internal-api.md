# API interna

saga no expone API de red pública. Sus "APIs" son: **endpoints HTTP locales del orbe**,
**protocolos de socket Unix** entre procesos, **la API de LiveKit** (modo room) y los
**modelos de datos** en archivos.

> Referencia de las interfaces internas, verificada contra el código.

## HTTP — orbe (`orb/orb_server.py`, `127.0.0.1:8777`)

Stdlib only salvo `/token`, que importa `livekit.api` lazy (solo lo toca ese handler).
Auth opcional por `ORB_TOKEN` (vacío = sin auth, local). Solo loopback.

| Método | Path | Qué hace | Respuesta |
|--------|------|----------|-----------|
| GET | `/` (o `/index.html`) | sirve `orb.html` | HTML |
| GET | `/vendor/...` | Three.js vendorizado (path traversal bloqueado; `.mjs`→`text/javascript`) | JS/CSS o 404 |
| GET | `/healthz` | probe de readiness | `200 "ok"` |
| GET | `/events` | stream SSE del estado (cola por cliente, ping 15s) | `text/event-stream` |
| GET | `/token?identity=&room=` | mintea el JWT con que el browser se une al room (modo room) | `{url, token, room}` / `500` |
| POST | `/state?s=<estado>` | setea el estado actual (lo postean los procesos de voz) | `204` |
| POST | `/attach?kind=image` | imagen pegada → dead-drop `/tmp/saga-attach.png` (body vacío borra) | `204` |
| POST | `/stage` | texto del textarea → reenvía `stage <b64>` al socket de control | `204` |
| POST | `/say` | prompt por texto (Shift+Enter) → reenvía `say <b64>` al socket | `204` / `503` |

Estados válidos: `idle, rec, transcribe, screen, think, speak, nueva, error, cancel, attach`
(inválido → normaliza a `idle`).

### `GET /token` (modo room, Ciclo 4)

Emite el JWT con el que el cliente browser se une al room de `livekit-server`. Query opcional:
`identity` (default `saga-client`), `room` (default `LIVEKIT_ROOM` = `saga`).

```json
{ "url": "ws://127.0.0.1:7880", "token": "<jwt>", "room": "saga" }
```

Mintea con `livekit.api.AccessToken` (import lazy): `.with_identity()` + `.with_grants(VideoGrants(room_join=True, room=...))`.
El token es **solo para unirse al room**: NO despacha. El dispatch del worker es AUTOMÁTICO (U8) — cuando el
browser se une al room "saga" lo CREA y el server despacha el worker solo (`@server.rtc_session()` sin
`agent_name`). Sin `LIVEKIT_API_KEY`/`SECRET` → `500`.

## Socket de control del agente — `LK_CTL_SOCK` = `/tmp/saga-lk-ctl.sock` (0o600)

Protocolo: una línea `verbo [payload_b64]\n` → `ok\n` / `err\n`. Lo crea el worker en `entry()`
(`asyncio.start_unix_server`), recién al despacharse al room (dispatch automático disparado por el browser al
unirse) → el socket existe solo cuando el agente ya entró (lo que `vcctl` espera como readiness, DESPUÉS de
abrir el browser).

- `press` (o `toggle`) — Win+Z. Acción según fase: idle→grabar, rec→cortar y mandar, busy→matar.
- `stage <b64>` — setea/limpia el texto staged (memoria del agente, vía `vc/attach.stage_text`).
- `say <b64>` — dispara un turno inmediato con ese texto (vacío → `err`).

**Owner**: `lk/agent.py` (handler `_handle` → `_press`/`_say`/`stage_text`). **Clientes**:
`vc/app._livekit_toggle` (Win+Z, manda `press`), `orb_server._forward_ctl` (panel: `stage`/`say`).
El socket lo crea el worker recién al despacharse al room → existe solo cuando el agente ya entró. Con
`close_on_disconnect=False` (U8) recargar/cerrar la pestaña del orbe NO mata la sesión ni el socket.

## Socket del cerebro Claude — `CLAUDE_SOCK` = `/tmp/saga-claude.sock` (0o600)

Protocolo: newline-delimited JSON.
- **req**: `{"prompt": "...", "image_b64": "<png b64 opcional>"}` | `{"reset": true}`
- **resp**: `{"delta": "..."}\n` … `{"done": true}\n` | `{"error": "..."}\n`

**Cancelación = el cliente cierra el socket.** Cuando `send_delta` falla al escribir (socket cerrado),
el daemon **MATA el grupo entero del turno en curso** (claude + subspawns de claude-mem) → daemon
libre, sin zombie ni huérfanos. El próximo turno respawnea con `--resume`: el contexto hasta el
último turno COMPLETO se mantiene (el abortado no se guardó). Si `--resume` cae ("No conversation
found"), respawnea con sesión fresca y reintenta una vez.

**Owner**: `claude_daemon.py`. **Cliente**: `vc/claudecli`.

## LiveKit (modo room, único — Ciclo 4)

Único transporte: worker headless conectado a un `livekit-server`
NATIVO local (no Docker: el NAT rompía el WebRTC). El audio llega por el track del browser cliente.

### Constantes (`vc/config.py`, `.env.local` cargado al importar)

| Constante | Default | Qué es |
|-----------|---------|--------|
| `LIVEKIT_URL` | `ws://127.0.0.1:7880` | URL de signaling (loopback) |
| `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` | `""` (secreto, `.env.local`) | credenciales para mintear/llamar la API |
| `LIVEKIT_ROOM` | `saga` | nombre del room |
| `LIVEKIT_SERVER_BIN` | `~/.local/bin/livekit-server` | binario del server (lo levanta `saga-ctl`) |
| `LIVEKIT_CONFIG` | `livekit.yaml` | config del server (bind loopback) |
| `LIVEKIT_SIGNAL_PORT` | `7880` | puerto de signaling (readiness del server) |

Las keys viven SOLO en `.env.local` (gitignored). `vc/config` carga `.env.local` con `python-dotenv`
al importarse → cualquier importador (worker, `orb_server` en `/token`) ve las keys.

### API de LiveKit usada

- **Token de cliente** (`orb_server._serve_token`): `AccessToken` + `VideoGrants(room_join)` →
  `.to_jwt()`. Solo para unirse; NO despacha.
- **Dispatch AUTOMÁTICO nativo** (U8): el worker se registra con `@server.rtc_session()` SIN `agent_name`,
  sobre un `AgentServer(load_fnc=lambda: 0.0, drain_timeout=0, num_idle_processes=1)`. Cuando el browser se
  une al room "saga", lo CREA y el server despacha el worker solo → `entry()` → socket de control. Ya NO se
  despacha por API (`_ensure_agent_dispatched` se eliminó de `vcctl.py`). Defensa: `lk/agent.py` hace
  `os.environ.pop("LIVEKIT_AGENT_NAME", None)` antes de crear el server (si esa env existiera, el SDK forzaría
  explicit dispatch). `load_fnc=0` → el worker nunca se auto-marca `unavailable` (era la causa raíz del
  Win+Z `FileNotFoundError` intermitente: el prod `load_threshold=0.7` shedeaba bajo la carga de arranque).

## Modelos de datos

No hay ORM ni base de datos. Modelos = formas JSON en archivos/sockets.

### `session.json`
```json
{ "id": "<uuid de la sesión de Claude>", "last_used": 1234567890.0 }
```
Escritura atómica (tmp + `os.replace`). Si está corrupto, rota a uuid nueva.

### Mensaje de turno a Claude (stream-json)
```json
{"type":"user","message":{"role":"user","content": "<str | [image, text]>"}}
```
`content` es array para multimodal (imagen base64 PNG + texto).

### `word_aliases.json` (opcional, editable)
Dict `palabra → fonetización`, aplicado en `clean_for_tts`.

### Estado del orbe
Un string de `VALID_STATES` (ver tabla arriba).
