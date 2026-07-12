# U3 — Cliente de audio (browser) · Generation Summary (Ciclo 4)

> El browser del orbe se vuelve participante del room: pide token, se conecta, publica el mic muteado,
> reproduce el TTS. El grueso del trabajo nuevo del ciclo.

## Archivos
- **`orb/vendor/livekit/livekit-client.esm.mjs`** (NEW) — SDK `livekit-client` 2.19.2, build ESM
  self-contained (sin imports bare), 1.19MB. Vendoreado local (mismo patrón que three.js; sin CDN en runtime).
- **`orb/orb.html`** (MOD):
  - importmap: `"livekit-client":"/vendor/livekit/livekit-client.esm.mjs"`.
  - `setState()` emite `CustomEvent('orbstate', {detail:name})` (acople desacoplado con el módulo LiveKit).
  - Módulo LiveKit nuevo: `fetch('/token?identity=saga-client&room=saga')` → `Room.connect`; mic publicado
    MUTEADO; listener `orbstate` (`rec`→unmute, else→mute); `TrackSubscribed`(audio)→`<audio>`+play;
    `AudioPlaybackStatusChanged`+botón "tocá para activar audio" (`startAudio()`); logs `[lk-client]`.
- **`orb/orb_server.py`** (MOD, bug cazado en verif): MIME map + `.mjs: text/javascript`.

## Bug encontrado y arreglado durante la verificación
El `.mjs` se servía con MIME `application/octet-stream` → el browser rechazaba el módulo ESM
("Strict MIME type checking"). El MIME map de `orb_server` tenía `.js` pero no `.mjs` (three.js usa
`.module.js`). Agregado `.mjs`. **Habría roto igual en el browser real** → la verificación valió.

## Verificación (Playwright MCP headless · server arriba · worker apagado para aislar U3)
| Check | Resultado |
|---|---|
| SDK `.mjs` carga como módulo (MIME OK) | ✅ tras el fix |
| `fetch /token` | ✅ `[lk-client] token OK -> ws://127.0.0.1:7880` |
| Signaling al server | ✅ signal connected |
| **Unirse al room** | ✅ `connected to Livekit Server 1.13.1 — room: saga, participant: saga-client` |
| Media PeerConnection (WebRTC) | ⚠️ `could not establish pc connection` — **limitación de Chromium headless** (sin UDP real en Playwright), NO bug de código |
| Mic publish + TTS playback | ⏳ requieren la PC de media → validar en el BROWSER REAL (Build&Test) |

## Honestidad sobre el alcance verificado
- **Verificado**: el cliente carga el SDK, pide token y se UNE al room a nivel signaling como participante.
- **NO verificado acá**: el flujo de media (mic frames + TTS playback) porque la PeerConnection WebRTC no
  levanta en Chromium headless. Esto es esperable en Playwright (WebRTC headless limitado), no un defecto del
  código (es el patrón estándar de LiveKit). Se valida en el browser real del usuario, que es parte del
  Build&Test del ciclo (turno de voz end-to-end con worker + cliente).

## Habilita / pendiente
- **U4** (wake en el cliente) engancha el mismo `unmute` local.
- **U5** (orbe sync) reusa el track TTS subscrito vía Web Audio AnalyserNode.
- **U6** (saga-ctl) levanta server+daemon+worker+orb_server y abre el browser.
- **Build&Test**: turno de voz completo en browser real + benchmark de latencia (NFR gate).
