# U8 — Dispatch consistente del agente LiveKit (auto-dispatch nativo)

> AI-DLC · CONSTRUCTION · Functional Design. Brownfield. Unidad de hardening del transporte room (Ciclo 4).
> Reemplaza de raíz el bug "coin-flip del dispatch" (Win+Z `FileNotFoundError` / `ConnectionRefusedError`
> intermitente en `saga-ctl start`).

## 1. Problema (causa raíz, MEDIDA — no supuesta)

Síntoma: `saga-ctl start` levanta server+claude+orb+worker pero el `create_dispatch` (paso 4.5) falla
intermitente con `TwirpError 503 "no response from servers"` → el agente no entra al room → no hay socket
de control → Win+Z `FileNotFoundError`. "A veces anda, a veces no" (coin-flip).

Diagnóstico por experimentos (no por memoria):
- **Cold-start LIMPIO (server fresco + worker fresco): `create_dispatch` OK en 0.0s, agente en el room,
  socket responde en ~0s. Funciona perfecto.** → el bug NO es timing/warm-up del server (descarta el "fix"
  del paso 3.5 con `list_dispatch`, ya eliminado, y el retry de 90s, también a descartar).
- En el log del worker, con saga corriendo: `"worker is at full capacity, marking as unavailable"` oscilando
  con `"below capacity, marking as available"`.
- En el SDK (`livekit/agents/worker.py:147`): `_default_load_threshold = ServerEnvOption(dev_default=inf,
  prod_default=0.7)`. El worker se lanza con `lk/agent.py start` = **modo producción** → `load_threshold=0.7`
  → el worker calcula su carga de CPU y **se auto-marca `unavailable` cuando supera 0.7**.

**Causa raíz:** en una laptop de un solo usuario, la carga local (inference + claude + browser + TTS) cruza
0.7 → el worker se saca de disponible → si el `create_dispatch` cae en esa ventana, el server no encuentra
worker en el topic → `503 no response from servers`. Un worker reusado y ya saturado queda `unavailable`
fijo → falla siempre. **El `load_threshold` es un mecanismo de load-shedding para POOLS de muchos workers;
saga es 1 worker dedicado para 1 usuario → no aplica, es contraproducente.**

Bugs secundarios detectados en la misma investigación:
- **S2 — Dispatch explícito innecesario.** El worker usa `agent_name="saga"` (`agent.py:113`) → exige
  dispatch explícito por API (`_ensure_agent_dispatched` + retries + probes en `vcctl.py`). Doc oficial del
  SDK (`worker.py:218`): *"Set agent_name to enable explicit dispatch. When explicit dispatch is enabled,
  jobs will not be dispatched to rooms automatically."* Saga (1 room fijo, 1 agente, sin metadata) es el caso
  de **dispatch automático**. El dispatch explícito es complejidad que sólo agrega puntos de falla.
- **S3 — Reuso de procesos en estado inconsistente.** `_start_room` reusa server/worker vivos ("YA corría")
  sin verificar coherencia. Un worker vivo apuntando a un server reiniciado, o saturado, queda fantasma.
- **S4 — Socket de control atado al JOB (bug latente).** El socket Unix de Win+Z (`LK_CTL_SOCK`) se crea
  DENTRO de `entry()` (`agent.py:378`), que corre por-JOB. `RoomInputOptions.close_on_disconnect=True`
  (default, SDK `room_io/types.py:265`) → cuando el browser se recarga/cierra, la sesión se cierra → el job
  muere → socket stale → Win+Z `ConnectionRefusedError`. Confirmado en vivo (10:07).

## 2. Diseño (4 cambios, todos con API nativa de LiveKit; cero parches, cero libs tocadas)

### Cambio 1 — Worker dedicado siempre disponible (EL fix de raíz)
`lk/agent.py`: construir el `AgentServer` con una función de carga fija que reporte 0 →
nunca se marca `unavailable`.
```python
server = AgentServer(load_fnc=lambda: 0.0)   # worker dedicado single-tenant: jamás "full capacity"
```
- `load_fnc` es parámetro PÚBLICO del `AgentServer` (`worker.py:326`). Reporta carga 0 siempre → el worker
  queda permanentemente `available` → el dispatch SIEMPRE encuentra worker en el topic. Elimina el coin-flip.
- No se toca `load_threshold` (en prod debe ser <1; con `load_fnc=0` el threshold es irrelevante).

### Cambio 2 — Dispatch AUTOMÁTICO nativo (elimina el frankenstein del dispatch explícito)
- `lk/agent.py:113`: `@server.rtc_session()` **sin `agent_name`** → dispatch automático. Defensa extra:
  `os.environ.pop("LIVEKIT_AGENT_NAME", None)` antes de crear el server (el SDK fuerza explicit dispatch si
  esa env existe — `worker.py:517`; hoy no está, pero lo blindamos).
- `vcctl.py`: ELIMINAR `_ensure_agent_dispatched()` (210-270) y su llamada (paso 4.5), y todo lo de
  `list_dispatch`/`create_dispatch`/retries. El browser, al unirse al room "saga", lo crea → el server
  auto-despacha el worker → `entry()` corre → socket. saga-ctl ya NO despacha nada por API.
- `vc/config.py`: eliminar `LIVEKIT_AGENT_NAME` (queda sin uso). `orb_server.py /token` no cambia (ya sólo
  mintea JWT con `room_join`; nunca despachó tras U7.1).

### Cambio 3 — `start` con estado coherente (gestión de procesos/concurrencia)
- **No reusar piezas acopladas potencialmente rotas.** El `livekit-server` se relanza FRESCO en cada `start`
  (los rooms viven en memoria del server → server fresco = sin rooms zombie → el primer browser crea el room
  limpio → auto-dispatch garantizado). El worker también fresco. Se reusan claude_daemon + orb (procesos
  sanos, independientes y caros de levantar) si ya corren.
  - Implementación: `_start_room` baja server+worker viejos (si hay) y los relanza. Reescribe la lógica
    "YA corría" para server/worker → siempre frescos; conserva el dedup-safe de claude/orb.
- **Drain corto para `stop` rápido.** `AgentServer(..., drain_timeout=0)`: hoy el worker, al recibir SIGTERM,
  entra en "draining 1800s" y puede sobrevivir ocupando el :8081, bloqueando el próximo start. Con
  `drain_timeout=0` el worker cierra al toque. `stop` sigue SIGTERM→(3s)→SIGKILL por pid exacto (ya correcto,
  no toca el `claude` de la sesión). Esto cierra el "draining zombie ocupa 8081".

### Cambio 4 — Socket de control de Win+Z robusto ante reconexión del browser
`lk/agent.py`: `session.start(..., room_input_options=RoomInputOptions(close_on_disconnect=False))`.
- Nativo (`room_io/types.py:265`). Al recargar/cerrar la pestaña, la sesión NO se cierra → el job sigue vivo
  → el socket persiste → al reconectar (misma identity `saga-client`), el agente sigue ahí. Mata el
  `ConnectionRefusedError`.
- El socket sigue naciendo en `entry()` (por-job), pero ahora el job es estable (no muere con el browser),
  así que no hace falta moverlo a nivel-worker (eso requeriría IPC entre proceso worker y proceso-job →
  complejidad innecesaria; `close_on_disconnect=False` lo resuelve de forma nativa y simple).

## 3. Flujo de arranque rediseñado (auto-dispatch)
```
saga-ctl start:
  1. livekit-server FRESCO (mata viejo) → rooms vacíos (sin zombies). Espera :7880.
  2. prewarm claude (dedup) + orb (dedup, open_browser=False). Espera sockets.
  3. worker FRESCO (lk/agent.py start): load_fnc=0 (always available), auto-dispatch, drain_timeout=0.
     Espera "registered worker".
  4. abre el browser → se une al room "saga" → lo crea → server AUTO-despacha el worker → entry() → socket.
  5. espera a que LK_CTL_SOCK responda (readiness REAL del agente en el room). Listo.
```
Diferencia clave vs hoy: el dispatch lo dispara la entrada del browser (paso 4), no una llamada API previa.
El browser es el trigger natural del room. Sin cliente no hay sesión (correcto). `_wait_ready(socket)` va
DESPUÉS de abrir el browser.

## 4. Archivos afectados
| Archivo | Cambio |
|---|---|
| `lk/agent.py` | `AgentServer(load_fnc=lambda:0.0, drain_timeout=0)`; `@server.rtc_session()` sin agent_name; `pop` env defensivo; `RoomInputOptions(close_on_disconnect=False)` en `session.start`. |
| `vcctl.py` | Eliminar `_ensure_agent_dispatched` + llamada; reordenar `_start_room` (browser antes del wait-socket); server+worker siempre frescos; sacar imports/refs de dispatch. |
| `vc/config.py` | Eliminar `LIVEKIT_AGENT_NAME` (sin uso). |
| `docs/*.md`, `.claude/CLAUDE.md`, `orb_server.py` (comentario) | Actualizar a "auto-dispatch nativo". Borrar la doc de dispatch explícito/`list_dispatch`/cold-start envenenado (desinformación). |

## 5. Verificación (proporcional, sin runtime de audio desde acá)
- `py_compile` de todo + import smoke + suite `tests.test_pure`.
- Smoke de arranque headless: server fresco + worker (load_fnc=0, auto-dispatch) + crear room por API
  (simula el browser) → verificar que `entry()` corre y `LK_CTL_SOCK` responde, SIN ningún create_dispatch.
- Repetir el smoke 3 veces seguidas (cold) → debe andar las 3 (no coin-flip).
- Validación en vivo del usuario (Win+Z + recargar pestaña → Win+Z sigue andando).

## 6. Riesgos / mitigaciones
- **Auto-dispatch y room pre-existente (pestaña zombie):** mitigado por Cambio 3 (server fresco resetea
  rooms). Si el usuario abre una pestaña con el server ya arriba y room creado por otra previa: el server
  fresco de cada `start` evita ese estado.
- **close_on_disconnect=False y sesiones colgadas:** si el browser se va para siempre, la sesión queda viva
  (idle). Aceptable: saga es mono-usuario; `stop` baja todo. El watchdog del orbe ya vuelve a idle visual.
- **load_fnc=0 enmascara saturación real:** irrelevante para 1 worker/1 usuario local (no hay balanceo).
