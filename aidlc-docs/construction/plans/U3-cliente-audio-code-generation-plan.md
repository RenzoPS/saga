# U3 — Cliente de audio (browser) · Code Generation Plan (Ciclo 4)

> Fuente única de verdad para Code Generation de U3. El browser del orbe se vuelve PARTICIPANTE del room:
> pide token, se conecta, publica el mic on-demand, recibe el track TTS y lo reproduce. Es el grueso del
> trabajo nuevo del ciclo. Depende de U1 (token + server) y U2 (worker que publica el TTS).

## Decisiones técnicas (clave — revisar)
1. **SDK**: `livekit-client` **2.19.2** (última en npm al 2026-06-23), build ESM
   (`dist/livekit-client.esm.mjs`). Se **vendorea local** en `orb/vendor/livekit/` (mismo patrón que three.js
   → offline, localhost, sin CDN en runtime) + entrada en el `importmap` (`"livekit-client"`).
2. **Conexión**: al cargar, `fetch('/token?identity=saga-client&room=saga')` → `{url, token}` →
   `Room.connect(url, token)`. Auto-reconnect nativo del SDK.
3. **Gate de publicación del mic = el estado del orbe (SSE), sin canal de control nuevo**. El browser publica
   el track de mic al unirse pero **arranca MUTEADO** (privacidad: un track muteado NO transmite audio). El
   orbe ya recibe el estado por SSE; engancho ahí: estado `rec` → `track.unmute()`; cualquier otro → `mute()`.
   Flujo: Win+Z/wake → worker `_press` → `set_audio_enabled(True)` + `orb_state("rec")` → SSE → browser
   desmutea. Doble gate (worker attach + browser mute) pero el mute es el mecanismo de privacidad. Evita la
   latencia de publicar/despublicar el track en cada turno (mute/unmute es instantáneo).
4. **Reproducir el TTS**: `RoomEvent.TrackSubscribed` (audio) → `track.attach()` → `<audio>` que reproduce la
   voz de saga. **Autoplay**: los browsers bloquean audio sin gesto del usuario → manejar
   `RoomEvent.AudioPlaybackStatusChanged` + un handler de click ("tocá para activar audio") que llama
   `room.startAudio()`. (U5 reusará este mismo track con Web Audio AnalyserNode para el orbe sync.)
5. **Acople con el orbe sin romper orden de carga**: `setState()` (en el módulo del orbe) emite un
   `CustomEvent('orbstate', {detail:name})`. El módulo LiveKit (separado) escucha ese evento para el gate de
   mute. Desacoplado, sin depender de qué módulo carga primero.

## Archivos afectados
| Archivo | Acción | Detalle |
|---|---|---|
| `orb/vendor/livekit/livekit-client.esm.mjs` | NEW | SDK vendoreado (2.19.2 ESM) |
| `orb/orb.html` | MOD | importmap (+`livekit-client`) · módulo LiveKit nuevo (connect/publish/subscribe/unlock) · `setState` emite `CustomEvent('orbstate')` |

## Lo que NO hace U3 (otras unidades)
- **Wake en el cliente** (onnxruntime-web) → U4. En U3 el gate de publicación es el estado `rec` (Win+Z ya lo
  produce). El wake lo agregará U4 enganchando el mismo `unmute`.
- **Orbe sincronizado con el TTS real** (AnalyserNode) → U5. U3 solo reproduce el track.
- **Orquestación** (saga-ctl levanta todo + abre el browser) → U6.

## Riesgos / mitigación
- **Permiso de micrófono** (getUserMedia): el SDK lo pide al crear el track local → prompt una vez al cargar.
  Aceptable (es el cliente de escritorio del usuario).
- **Autoplay del audio**: mitigado con `startAudio()` en un gesto + UI mínima de "activar audio".
- **Compatibilidad SDK**: worker = livekit-agents 1.6 (rtc 1.1.8); client 2.19.2 es la línea actual y compatible
  con el protocolo del server 1.13.1. Si hubiera mismatch de protocolo, el log del server lo diría (verif).
- **Privacidad**: el mic publica muteado; no sale audio hasta `rec`. Local-only (server loopback, U1).

---

# PART 1 — PLANNING (este documento)
- [x] Step 1: Analizar contexto (leído orb.html: SSE/setState/panel; versión SDK; flujo de estado)
- [x] Step 2: Plan con archivos exactos + decisiones técnicas
- [x] Step 3: Contexto (depende de U1 token/server + U2 worker TTS; interfaz = room `saga`, `/token`)
- [x] Step 4: Guardar este plan
- [x] Step 5: Resumir al usuario
- [x] Step 6: Log del prompt de aprobación en audit.md
- [x] Step 7: Esperar aprobación explícita → "Aprobar y generar" (tras explicación detallada)
- [x] Step 8: Registrar respuesta
- [x] Step 9: Marcar Part 1 completo

---

# PART 2 — GENERATION
- [x] **Step 10**: Vendoreado `livekit-client` 2.19.2 ESM → `orb/vendor/livekit/livekit-client.esm.mjs` (1.19MB, self-contained)
- [x] **Step 11**: `orb/orb.html` — importmap: `"livekit-client":"/vendor/livekit/livekit-client.esm.mjs"`
- [x] **Step 12**: `orb/orb.html` — `setState()` emite `CustomEvent('orbstate', {detail:name})`
- [x] **Step 13**: `orb/orb.html` — módulo LiveKit: fetch `/token` + `Room.connect`; mic publicado MUTEADO +
  listener `orbstate` (rec→unmute/else→mute); `TrackSubscribed`→attach `<audio>`; `AudioPlaybackStatusChanged`
  + botón unlock; logs `[lk-client]`.
- [x] **Step 13b** (BUG cazado en verif): `orb/orb_server.py` MIME map — agregado `.mjs: text/javascript`
  (se servía como `application/octet-stream` → el browser rechazaba el módulo. Habría roto también en prod).
- [~] **Step 14**: Verificación (Playwright MCP headless; server arriba, worker apagado)
  - [x] SDK `.mjs` carga (MIME OK tras el fix), sin errores de módulo
  - [x] `[lk-client] token OK`; signal connected; **`connected to Livekit Server room: saga participant:
    saga-client`** → el browser SE UNE al room a nivel signaling
  - [ ] **Media PeerConnection NO se estableció en headless** (`could not establish pc connection`) →
    limitación conocida de WebRTC en Chromium headless (Playwright sin UDP real), NO bug de código. El mic
    publish + TTS playback se validan en el BROWSER REAL del usuario (Build&Test del ciclo).
- [x] **Step 15**: Summary en `aidlc-docs/construction/U3-cliente-audio/code/generation-summary.md`
- [x] **Step 16**: Actualizar checkboxes + aidlc-state.md

## Criterio de "U3 hecho"
- El browser se conecta al room `saga` con el token de `/token`, publica el mic (muteado) y queda listo para
  recibir/reproducir el TTS.
- El gate de mute responde al estado `rec` del orbe (SSE).
- Sin errores JS en consola. Permiso de mic + unlock de audio manejados.
- **NO se valida** el turno de voz end-to-end (necesita worker corriendo + dispatch) → Build&Test del ciclo.
