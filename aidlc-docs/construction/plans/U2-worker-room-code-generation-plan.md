# U2 — Worker modo room · Code Generation Plan (Ciclo 4)

> Fuente única de verdad para Code Generation de U2. Brownfield: modificar, no duplicar.
> Migrar el worker `lk/agent.py` de `console` → `start` (conectado a livekit-server). El cerebro IA
> (STT/LLM/TTS/VAD/BVC/claude_daemon/Win+Z socket) se CONSERVA intacto.

## Hallazgo que achica U2
`lk/agent.py` ya usa el patrón moderno `AgentServer` + `@server.rtc_session()` + `agents.cli.run_app(server)`,
que soporta los subcomandos `console` Y `start` (livekit-agents 1.6.0). En `start`, el worker se registra
contra `LIVEKIT_URL/API_KEY/API_SECRET` (env, ya cargadas por `load_dotenv` en U1) y espera dispatch. Cuando
el browser (U3) entra al room `saga`, el server despacha el job → corre `entry()`. **No hay que reescribir el
entrypoint.** El grueso ya está bien.

## Confirmado en código (no asumido)
- `voice/room_io/_input.py:153-156`: `async for event in stream: if not self._attached: continue` → en room,
  con el stream detached (mic off vía `set_audio_enabled(False)`), **los frames se descartan**. Esto RESUELVE
  el buffer del Ciclo 3 sin tocar buffers a mano: es el mecanismo nativo del transporte room.

## Qué cambia de verdad (mínimo)
1. **Wake server-side → solo console**. Hoy `entry()` arranca `WakeWordDetector(on_wake=_press)` que abre el
   **mic local** del proceso (listener portaudio). En room el worker es **headless** (no tiene mic; el audio
   llega por el track del browser). Correr ese wake en room es incorrecto. → gatearlo a modo console. En room,
   el wake corre en el CLIENTE (U4, onnxruntime-web, pendiente). Log claro del cambio.
2. **Detección de modo**: `_CONSOLE_MODE = "console" in sys.argv`. Fuente de verdad = el subcomando con el que
   se lanza (`console` vs `start`). Sin flag nuevo.
3. **Docstring**: documentar modo room (cómo se corre, qué resuelve, dónde corre el wake ahora).

## Lo que NO cambia (se conserva)
- `ClaudeCodeLLM` (turn handler), Deepgram STT/TTS, Silero VAD, BVC, `claude_daemon`, prewarm, orbe.
- El socket `LK_CTL_SOCK` + Win+Z (`_press`/`_say`/`stage`). Funciona igual: en room, `set_audio_enabled`
  attacha/detacha el track del browser (con discard nativo). Win+Z sigue siendo el toggle.
- `_on_user_state` / `_on_agent_state` (máquina de fases) — la lógica de fases es transport-agnostic.
- `claude_llm.py` — NO se toca (es el cerebro; el transporte no lo afecta).

## Archivos afectados
| Archivo | Acción | Detalle |
|---|---|---|
| `lk/agent.py` | MOD | `_CONSOLE_MODE` (argv) · gatear `_wake` a console · log de transporte · docstring |

## Riesgos / mitigación
- **No se puede probar el flujo de audio completo sin U3** (no hay cliente publicando mic). El entregable de
  U2 es "el worker se registra y atiende el room". Verificación de U2 = el worker arranca en `start`, se
  REGISTRA contra el server local, y queda esperando dispatch. El audio end-to-end se valida en Build&Test
  (tras U3).
- **Auto-dispatch**: sin `agent_name`, el worker se asigna automáticamente a rooms nuevos → al entrar el
  browser a `saga`, despacha. No configuramos dispatch explícito (default alcanza).
- **No regresar console**: el modo console (fallback) queda intacto; el único cambio (wake gateado) lo
  conserva en console.

---

# PART 1 — PLANNING (este documento)
- [x] Step 1: Analizar contexto de U2 (leído agent.py + room_io/_input.py + versión LK)
- [x] Step 2: Plan con archivo exacto y cambios mínimos
- [x] Step 3: Contexto (depende de U1; habilita U3/U6; interfaz = worker registrado en ws://127.0.0.1:7880)
- [x] Step 4: Guardar este plan
- [x] Step 5: Resumir al usuario
- [x] Step 6: Log del prompt de aprobación en audit.md
- [x] Step 7: Esperar aprobación explícita → "Aprobar y generar"
- [x] Step 8: Registrar respuesta
- [x] Step 9: Marcar Part 1 completo

---

# PART 2 — GENERATION (tras aprobación)
- [x] **Step 10**: `lk/agent.py` — `_CONSOLE_MODE = "console" in sys.argv` (junto a `_WAKE_ENABLED`)
- [x] **Step 11**: `lk/agent.py` — wake server-side gateado a console (`if _WAKE_ENABLED and _CONSOLE_MODE`)
  + `elif` log: en room el wake corre en el cliente (U4)
- [x] **Step 12**: `lk/agent.py` — log de transporte al arrancar (`console`/`room`) + docstring actualizado
- [x] **Step 13**: Verificación
  - [x] `py_compile lk/agent.py` OK
  - [x] `lk/agent.py start` → `starting worker` → `registered worker` (url ws://127.0.0.1:7880), esperando
    dispatch; drenado al timeout (exit 124 = nuestro kill, no crash). Sin client = sin dispatch = sin claude.
  - [x] `console`: py_compile OK (no se puede correr headless sin device de audio; el cambio es trivial+gateado)
- [x] **Step 14**: Summary en `aidlc-docs/construction/U2-worker-room/code/generation-summary.md`
- [x] **Step 15**: Actualizar checkboxes + aidlc-state.md

## Criterio de "U2 hecho"
- `lk/agent.py start` registra el worker contra `ws://127.0.0.1:7880` y espera dispatch (sin crashear).
- `console` sigue intacto (fallback).
- El wake server-side ya no corre en room (queda para el cliente, U4).
- Audio end-to-end NO se valida acá (necesita U3) → Build&Test del ciclo.
