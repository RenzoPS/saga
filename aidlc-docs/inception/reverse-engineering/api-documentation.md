# API Documentation

saga no expone una API pública de red. Sus "APIs" son: **endpoints HTTP locales del orbe**,
**protocolos de socket Unix** entre procesos, y las **interfaces internas** clave. saga es
**ROOM-ONLY** (modo LiveKit + transporte room): el transporte console y el flujo clásico
`VOICE_LIVEKIT=0` fueron ELIMINADOS (Ciclo 4, U7). Se documentan las tres superficies vigentes.

## HTTP APIs (orbe — `orb/orb_server.py`, `127.0.0.1:8777`)

Solo loopback. Auth opcional por `ORB_TOKEN` (vacío = sin auth, local). Stdlib puro salvo `/token`,
que importa `livekit.api` de forma lazy (única dep pip del módulo, solo la toca ese handler).

### GET /  (y /index.html)
- **Purpose**: Servir la página del orbe (`orb.html`).
- **Response**: `text/html`. 500 si falta el archivo.

### GET /vendor/...
- **Purpose**: Servir Three.js + LiveKit JS SDK vendorizados. Path traversal bloqueado
  (resuelve dentro de `vendor/`; `.mjs` → `text/javascript`).
- **Response**: JS/CSS según extensión, o 404.

### GET /healthz
- **Purpose**: Probe de readiness (lo usa `vc/orb.ensure_orb`).
- **Response**: `200 "ok"`.

### GET /events
- **Purpose**: Stream SSE del estado actual (canal confiable, cola por cliente).
- **Response**: `text/event-stream`; `data: <estado>\n\n` al conectar y en cada cambio;
  `: ping` cada 15s. Estados válidos: idle, rec, transcribe, screen, think, speak, nueva,
  error, cancel, attach.

### GET /token?identity=&room=  (modo room, Ciclo 4)
- **Purpose**: Emitir el JWT con el que el cliente browser se une al room de `livekit-server`.
- **Request**: query opcional `identity` (default `saga-client`), `room` (default `LIVEKIT_ROOM` = `saga`).
- **Response**: `application/json` `{"url": "ws://127.0.0.1:7880", "token": "<jwt>", "room": "saga", "wake": <bool>}`.
  `500` si faltan `LIVEKIT_API_KEY`/`SECRET` o si falla el minteo.
- **Detalle**: mintea con `livekit.api.AccessToken` + `VideoGrants(room_join=True, room=...)`. El token es
  **solo para unirse al room**: NO despacha. El dispatch del worker es AUTOMÁTICO nativo (U8) — al unirse el
  browser CREA el room "saga" y el server despacha el worker solo (`@server.rtc_session()` sin `agent_name`).
  `wake` (U4): si es `true` el cliente publica el mic DESMUTEADO siempre (el server oye "hey saga");
  refleja `SAGA_WAKE_ENABLED`.

### POST /state?s=<estado>
- **Purpose**: Setear el estado actual (lo postea `vc/orb.orb_state` desde los procesos de voz).
- **Request**: query `s` = nombre de estado (se normaliza; inválido -> idle).
- **Response**: `204`.

### POST /attach?kind=image
- **Purpose**: Adjuntar imagen pegada desde el panel (dead-drop).
- **Request**: body binario = PNG. Body vacío -> borra el adjunto. `kind != image` -> 400.
- **Response**: `204`. Escribe `/tmp/saga-attach.png` (0o600). Claude la lee de disco como `screenshot_path`.

### POST /stage
- **Purpose**: Autosave del textarea del panel -> stagea texto en la MEMORIA del agente (no filesystem).
- **Request**: body = texto (puede ser vacío -> limpia el staged).
- **Response**: `204`. Reenvía `stage <b64>` al socket de control del agente.

### POST /say
- **Purpose**: Prompt por texto (Shift+Enter) -> dispara un turno inmediato sin grabar voz.
- **Request**: body = texto (no vacío). Vacío -> 204 sin disparar.
- **Response**: `204`, o `503` si el agente LiveKit no responde. Reenvía `say <b64>` al socket.

## Socket APIs (Unix)

### Socket de control del agente LiveKit — `LK_CTL_SOCK` = `/tmp/saga-lk-ctl.sock` (0o600)
Protocolo: una línea de texto `verbo [payload_b64]\n` -> respuesta `ok\n` / `err\n`.
- `press` (o `toggle`): Win+Z. Acción según fase — idle->grabar, rec->cortar y mandar, busy->matar.
- `stage <b64>`: setea/limpia el texto staged (memoria del agente, vía `vc/attach.stage_text`).
- `say <b64>`: dispara un turno inmediato con ese texto (mismo LLM+TTS; vacío -> `err`).
- **Owner**: `lk/agent.py` (handler `_handle` -> `_press`/`_say`/`stage_text`); el worker lo crea en `entry()`
  recién al despacharse al room, así que el socket existe solo cuando el agente ya entró. **Clientes**:
  `vc/app._livekit_toggle` (Win+Z, manda `press`), `orb_server._forward_ctl` (panel: `stage`/`say`).
  Con `close_on_disconnect=False` (U8) recargar/cerrar la pestaña del orbe NO mata la sesión ni el socket.

### Socket del cerebro Claude — `CLAUDE_SOCK` = `/tmp/saga-claude.sock` (0o600)
Protocolo: newline-delimited JSON.
- **req**: `{"prompt": "...", "image_b64": "<png b64 opcional>"}`  |  `{"reset": true}`.
- **resp**: `{"delta": "..."}\n` (stream) ... `{"done": true}\n`  |  `{"error": "..."}\n`.
- **Cancelación = el cliente cierra el socket.** Al fallar la escritura del delta el daemon MATA el grupo
  entero del turno en curso (claude + subspawns de claude-mem) y respawnea con `--resume` (contexto intacto);
  si `--resume` cae ("No conversation found") arranca sesión fresca y reintenta una vez.
- **Owner**: `claude_daemon.py`. **Cliente**: `vc/claudecli` (`_ask_via_daemon`, `reset_claude`).

## Internal APIs (interfaces Python clave)

### vc.claudecli.ask_claude_stream(prompt, on_first_token=None, screenshot_path=None) -> Iterator[str]
- **Purpose**: Stream de text_deltas de Claude. Daemon primero; one-shot `claude -p` si falla. Imagen va al one-shot.
- **Parameters**: `prompt` (str), `on_first_token` (callback al 1er token), `screenshot_path` (Path|None).
- **Return**: Iterador bloqueante de strings (deltas de texto).

### vc.claudecli.reset_claude() / prewarm_claude()
- **Purpose**: Resetear sesión (daemon o archivo) / spawnear el daemon sin bloquear (dedup-safe).

### lk.claude_llm.ClaudeCodeLLM(llm.LLM).chat(...) -> LLMStream
- **Purpose**: Adaptar Claude al contrato LLM de LiveKit. ÚNICO turn handler: los comandos de voz se
  enganchan acá reusando helpers de `vc/` (`is_reset_command`, `is_visual_command`, `take_staged`).

### vc.session
- `get_active_session_id() -> (uuid, is_new)`; `reset_session() -> uuid`; `touch_session()`.
- `is_reset_command(text) -> bool`; `is_visual_command(text) -> bool`.

### vc.attach
- `stage_text(text)`; `clear_text()`; `has_staged() -> bool`; `take_staged() -> (text|None, imgPath|None)`.

### vc.guard.denied(cmd) -> str|None
- **Purpose**: Etiqueta del patrón catastrófico si el comando matchea (función pura, testeable).

> Nota: el TTS lo maneja el pipeline de LiveKit (Deepgram Aura-2 / edge-tts fallback). Los helpers
> propios de TTS (`clean_for_tts`/`stream_to_sentences`/`TTSStreamer` de `vc/tts.py`) fueron
> ELIMINADOS en U7 junto con el flujo clásico; ya no existen en el código.

## Data Models

No hay ORM ni esquema de base de datos. Modelos de datos = formas JSON en archivos/sockets.

### session.json
- **Fields**: `id` (uuid de la sesión de Claude), `last_used` (epoch float).
- **Validation**: si está corrupto, rota a uuid nueva (atomic write tmp + os.replace).

### Mensaje de turno a Claude (stream-json)
- **Fields**: `{"type":"user","message":{"role":"user","content": <str | [image, text]>}}`.
- **Relationships**: `content` array para multimodal (imagen base64 PNG + texto).

### Estado del orbe
- **Fields**: un string de `VALID_STATES`. Inválido -> normaliza a `idle`.
