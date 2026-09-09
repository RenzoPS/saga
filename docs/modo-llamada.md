# Modo llamada

Conversación continua en vez de push-to-talk: la línea se abre **una** vez y queda abierta. El fin
de cada turno lo decide **Deepgram Flux** con señales acústicas y lingüísticas, en vez de un piso
fijo de silencio que se paga entero en cada turno.

```bash
SAGA_MODE=call saga-ctl start
```

- **Win+Z** levanta el tubo (orbe `◉ En línea`, cian) y **Win+Z** vuelve a colgar.
- La fase **nunca vuelve a `idle`** entre turnos — eso es lo que lo separa de un walkie-talkie.
- Cuelga sola tras `SAGA_CALL_IDLE_TIMEOUT_S` (180s) sin actividad.

Para el detalle de las fases y los filtros de interrupción, ver [`turn-flow.md`](turn-flow.md).
Para por qué el contexto es de Claude y no de LiveKit, ver [`architecture.md`](architecture.md).

## Lo que anda, medido

Todo lo de abajo está verificado con voz sintética end-to-end, no leído de la doc.
El arnés es `scripts/e2e_llamada.sh`: levanta un Chromium headless con micrófono FALSO
alimentado por un `.wav`, abre la línea por el socket de control y lee `saga.log`.

### Una llamada de verdad: dos turnos sin tocar nada

```
02:58:37   ▎ Win+Z -> LLAMADA ABIERTA
02:58:42  EOUMetrics end_of_utterance_delay=0.533s
02:58:42  claude prompt: '...qué hora es.'
02:58:42  agent_state -> thinking (phase=call)
02:58:44  [lk] tool -> Bash                          ← lo agéntico sigue intacto
02:58:48  [claude dice] Son las 1:58 de la madrugada.
02:58:52  agent_state -> listening (phase=call)      ← la línea NO se cierra
02:59:00  EOUMetrics end_of_utterance_delay=0.944s
02:59:00  claude prompt: 'Perfecto, ahora contame un chiste bien corto.'
02:59:02  [claude dice] ¿Por qué el programador se quedó sin novia? …
02:59:09  agent_state -> listening (phase=call)
```

Lo que importa es la columna `phase`: **nunca vuelve a `idle`**. En push-to-talk cada
transición apagaba el mic y te obligaba a apretar la tecla de nuevo.

### Latencia

| | Push-to-talk (tu medición) | Llamada |
|---|---|---|
| EOU delay | 1.202s (piso fijo) | **0.533 – 1.408s** (lo decide Flux) |
| LLM ttft | 3.322s | 1.502 – 3.282s |
| TTS ttfb | 0.265s | 0.241 – 0.323s |
| **Percibida** | **~4.79s** | **~2.73s en el mejor caso** |

El EOU ya no es un piso: cuando la frase está claramente terminada, Flux corta en 0.5s.
Cuando queda ambigua, se toma 1.4s. Eso es lo que un umbral fijo no puede hacer.

### Barge-in

Cortó una respuesta de ~30s a los 4 segundos y pasó a escuchar. El mecanismo funciona.

### El bug del volumen — encontrado y arreglado

`orb.html` hacía `attachRemoteAudio` en cada `TrackSubscribed` y **solo appendeaba**: no
había `TrackUnsubscribed` ni detach. Como `close_on_disconnect=False` mantiene viva la
pestaña, cada `saga-ctl restart` sumaba otro `<audio>` reproduciendo **el mismo track**.

Dos pipelines de playback sobre una sola fuente tienen jitter buffers independientes → se
desfasan unos milisegundos → interferencia destructiva. No suena a eco: suena a que el
volumen se desplomó de la nada. Que es literalmente cómo lo describiste.

Arreglado: cada attach limpia el anterior, y se limpian también los `AnalyserNode` huérfanos.

**Sin confirmar por oído.** El mecanismo es claro y el arreglo es correcto, pero yo no
puedo escuchar. Si vuelve a pasar, avisá.

### El bug de la sala — arreglado, con un desvío

`saga-ctl restart` con la pestaña abierta fallaba **siempre**. Medido:

```
00:32:41.106  room creado por el cliente
00:32:43.226  worker registrado          ← 2.1s tarde
```

El dispatch automático despacha al **crearse** el room. El cliente reconectaba antes que el
worker → no había evento pendiente → el agente no entraba nunca.

Primero lo hice por token (`RoomConfiguration.agents`), que es lo que documenta LiveKit.
**No funciona con este SDK**, y el server lo dice textual:

```
not dispatching agent job since no worker is available
  {"agentName": "saga", "jobType": "JT_PARTICIPANT"}
```

El token pide un job `JT_PARTICIPANT` y el SDK de Python sólo registra workers
`JT_ROOM`/`JT_PUBLISHER` (`ServerType` no tiene PARTICIPANT). Se ve bien, no rompe nada
visible, y el agente nunca entra.

Quedó por API (`vc/dispatch.py`), llamado desde `/token`: el agente se pide cuando el
cliente está por entrar. Hay un test que se rompe solo el día que el SDK agregue
`ServerType.PARTICIPANT`, para volver al camino simple.

---

## Fragilidad que arreglé del turno segmentado

Tres cosas que me preguntaste y eran reales:

1. **No había timeout.** El camino segmentado cancela a propósito el watchdog de 60s (el
   trabajo con tools es legítimamente largo). Si el daemon moría a mitad de turno, el
   drenado esperaba `_DONE` **para siempre**. Ahora hay un techo de silencio entre eventos.
2. **Dos consumidores de una cola.** `_next_text` y `_block` hacían `q.get()` cada uno.
   Funcionaba por serialización accidental. Ahora hay un dueño único (`_TurnReader`) y un
   test con AST que falla si alguien más toca la cola.
3. **El transcript llegaba tarde.** Se logueaba después del `wait_for_playout()` del último
   bloque: con 88s de audio, 88 segundos tarde. Ahora se loguea por bloque, al terminar de
   escribirse.

---

## Lo que NO hice, y por qué

**El orbe sigue siendo el nuestro.** Agregué un estado `listen` ("◉ En línea", cian) porque
mostrar "● Grabando" con la línea abierta es la misma clase de mentira que veníamos
arreglando. No migré a los componentes de LiveKit: mide mal el costo/beneficio a esta hora
—mete React + npm + build a un proyecto Python que hoy es un HTML sin build— y **no baja
latencia**, que era el objetivo. Los componentes existen (`AgentAudioVisualizerAura` es
literalmente un orbe shader) y la migración queda planteada, no hecha.

**"Que sepa dónde la cortaste" no está.** LiveKit ya trunca su historial a lo que
realmente escuchaste al interrumpir. No sirve todavía porque ignoramos el `chat_ctx`
(Claude mantiene su propia sesión). El trabajo no es implementarlo: es leer ese transcript
truncado y pasárselo a Claude. Es la próxima pieza natural.

**No toqué la sesión sin TTL** (lo que te sacó lo del feedback viejo) ni el **wake word con
threshold 0.08** (dispara con ruido: detecciones de confianza 0.13 y 0.19 contra un default
de 0.92 en el código). Los dos siguen ahí, anotados.

**No screenshots del orbe.** El chromium cacheado no escribe `--screenshot` ni `--dump-dom`
en este build. Probé headless nuevo y viejo. Abrilo y miralo.

**Dos hallazgos de diseño preexistentes** en `orb.html` que dejé como están: el `<img alt="">`
del chip de adjuntos (lo llena JS al pegar una imagen) y el glow del label. El glow es el
lenguaje visual del orbe; no toco diseño tuyo sin que lo pidas.

---

## Cómo probarlo

```bash
SAGA_MODE=call saga-ctl restart     # modo llamada
saga-ctl restart                    # push-to-talk (default, intacto)
```

En modo llamada: **Win+Z abre la línea, Win+Z cuelga.** Hablá cuando quieras, cortala
hablándole encima. Cuelga sola tras 180s sin actividad — puesto a propósito: un mic abierto
indefinidamente frente a una IA agéntica con permisos `auto` no es algo para dejar vivo
cuando no hay nadie.

Todo se puede tunear sin tocar código:

| Env | Default | Qué hace |
|---|---|---|
| `SAGA_MODE` | `ptt` | `call` para el modo llamada |
| `SAGA_CALL_IDLE_TIMEOUT_S` | `180` | cuándo cuelga sola |
| `SAGA_FLUX_EAGER_EOT` | `0.6` | **bajalo para más velocidad** (0.3–0.9) |
| `SAGA_FLUX_EOT` | `0.7` | confianza para cerrar el turno |
| `SAGA_FLUX_LANGUAGES` | `es,en` | hints de idioma |
| `SAGA_FLUX_KEYTERMS` | `Saga,Renzo,…` | nombres propios y jerga |

**La palanca que te va a interesar es `SAGA_FLUX_EAGER_EOT`.** Está en 0.6 (conservador) a
propósito: más bajo arranca a generar antes de que termines de hablar, pero cada falso
arranque es una cancelación de turno — el mismo camino que `turn-flow.md` documenta como el
que rompía todo con `preemptive_generation`. Bajalo midiendo, de a 0.1.

## Lo que no puedo validar yo

Que se **sienta** como una llamada. Probé con voz sintética de Aura-2, que es material duro
para cualquier STT: en un turno transcribió "Hola Saga, decime" como "sala de si me". Los
otros turnos salieron limpios. Tu voz real debería andar mejor, pero es una hipótesis.

Eso lo tenés que probar vos.
