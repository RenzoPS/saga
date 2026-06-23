# API interna

saga no expone API de red pública. Sus "APIs" son: **endpoints HTTP locales del orbe**,
**protocolos de socket Unix** entre procesos, y los **modelos de datos** en archivos.

> Referencia de las interfaces internas, verificada contra el código.

## HTTP — orbe (`orb/orb_server.py`, `127.0.0.1:8777`)

Auth opcional por `ORB_TOKEN` (vacío = sin auth, local). Solo loopback.

| Método | Path | Qué hace | Respuesta |
|--------|------|----------|-----------|
| GET | `/` | sirve `orb.html` | HTML |
| GET | `/vendor/...` | Three.js vendorizado (path traversal bloqueado) | JS/CSS o 404 |
| GET | `/healthz` | probe de readiness | `200 "ok"` |
| GET | `/events` | stream SSE del estado (cola por cliente, ping 15s) | `text/event-stream` |
| POST | `/state?s=<estado>` | setea el estado actual (lo postean los procesos de voz) | `204` |
| POST | `/attach?kind=image` | imagen pegada → dead-drop `/tmp/saga-attach.png` (body vacío borra) | `204` |
| POST | `/stage` | texto del textarea → reenvía `stage <b64>` al socket de control | `204` |
| POST | `/say` | prompt por texto (Shift+Enter) → reenvía `say <b64>` al socket | `204` / `503` |

Estados válidos: `idle, rec, transcribe, screen, think, speak, nueva, error, cancel, attach`
(inválido → normaliza a `idle`).

## Socket de control del agente — `/tmp/saga-lk-ctl.sock` (0o600)

Protocolo: una línea `verbo [payload_b64]\n` → `ok\n` / `err\n`.

- `press` (o `toggle`) — Win+Z. Acción según fase: idle→grabar, rec→cortar y mandar, busy→matar.
- `stage <b64>` — setea/limpia el texto staged (memoria del agente).
- `say <b64>` — dispara un turno inmediato con ese texto.

**Owner**: `lk/agent.py`. **Clientes**: `vc/app._livekit_toggle` (Win+Z), `orb_server._forward_ctl` (panel).

## Socket del cerebro Claude — `/tmp/saga-claude.sock` (0o600)

Protocolo: newline-delimited JSON.
- **req**: `{"prompt": "...", "image_b64": "<png b64 opcional>"}` | `{"reset": true}`
- **resp**: `{"delta": "..."}\n` … `{"done": true}\n` | `{"error": "..."}\n`

**Owner**: `claude_daemon.py`. **Cliente**: `vc/claudecli`.

## Socket del daemon Whisper — `/tmp/saga-whisper.sock` (0o600, flujo clásico)

Protocolo: newline-delimited JSON.
- **req**: `{"audio": "<path wav>", "lang": "es"}`
- **resp**: `{"ok": true, "text": "..."}` | `{"ok": false, "error": "..."}`

**Owner**: `whisper_daemon.py`. **Cliente**: `vc/stt`.

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
