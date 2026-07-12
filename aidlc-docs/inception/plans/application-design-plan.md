# Application Design Plan — Ciclo 4 (migración a modo room)

> Estado: **COMPLETO**. Preguntas respondidas por el AI (usuario delegó). Solo documentación.
> Fundamento arquitectónico: worker + room + frontend client es el patrón ESTÁNDAR de LiveKit Agents
> (confirmado con docs oficiales: docs.livekit.io/agents/overview, /build/anatomy).

## Checklist de artefactos
- [x] components.md — componentes y responsabilidades
- [x] component-methods.md — interfaces/métodos de alto nivel
- [x] services.md — orquestación (saga-ctl)
- [x] component-dependency.md — flujo de audio y dependencias
- [x] application-design.md — consolidado
- [x] Validación de consistencia

## Preguntas de diseño (respondidas — usuario delegó)

### Q1: ¿El cliente browser es nuevo o extiende el orbe actual?
**[Answer]: EXTIENDE el orbe actual.** Hoy el orbe ya es un browser (orb.html servido por orb_server) que
recibe estado por SSE. Se le agrega el **LiveKit JS SDK**: capturar mic + publicar track + suscribirse al
track TTS + animar con Web Audio. No es un cliente nuevo desde cero — es el orbe con capacidad de audio.

### Q2: ¿Dónde corre el wake word "hey saga"?
**[Answer]: En el CLIENTE (browser), con onnxruntime-web.** (CORREGIDO 2026-06-23 tras revisar el vault.)
El browser corre el wake localmente sobre el mic y SOLO publica el track al room cuando detecta "hey saga"
(o Win+Z). Razones (alineadas con la visión del vault — saga = "DesktopLayer como producto", cross-platform):
- Es el **patrón estándar de LiveKit**: el frontend maneja su propia media (captura + decide cuándo publicar).
- Alineado con la visión: el **cliente ES el producto** (orbe + hotkey + wake + screenshot viven juntos).
- **Privacidad** (local-first): el mic no sale hasta detectar la palabra.
- **Cross-platform**: cuando sea app de escritorio (Electron/Tauri), el wake ya vive en el cliente → portable.
- `hey_saga.onnx` (Ciclo 2, FPPH=0) carga en onnxruntime-web sin cambios — estándar, no frankenstein.
- Costo: portar el detector a JS/onnxruntime-web (trabajo nuevo, asumido como correcto vs el atajo del worker).
- **Descartado**: wake en el worker (mic transmite continuo, acopla el wake al backend, contra la visión).

### Q3: ¿Cómo se autentican cliente y worker al server (tokens)?
**[Answer]: Token-service local mínimo.** El server LiveKit requiere JWT firmados con el API_SECRET. Un
endpoint chico (en orb_server o un script de saga-ctl) genera el token del cliente browser. El worker usa
las keys directo. Todo local, las keys viven en `.env.local` (gitignored).

### Q4: ¿Win+Z sigue igual?
**[Answer]: SÍ.** El socket de control (`LK_CTL_SOCK`) y el flujo de fases se conservan en el worker.
Win+Z manda "press" al worker como hoy. El audio ahora viene del room, no de console.

### Q5: ¿saga-ctl orquesta todo?
**[Answer]: SÍ.** saga-ctl levanta: (1) livekit-server (Docker), (2) saga-worker (modo start), (3) abre
el browser cliente. Con readiness de cada pieza. El orbe deja de ser solo visual → es cliente de audio.

### Q6: ¿Console se elimina?
**[Answer]: NO, queda como fallback dev.** Selección por env/flag. Room = default. Console = debug sin server.

### Q7: ¿Estilo arquitectónico?
**[Answer]: El estándar de LiveKit** (worker stateful + room + frontend client + WebRTC). No inventar
patrones propios — seguir el canónico, que es mantenible/escalable/multi-cliente (web hoy, desktop mañana).
