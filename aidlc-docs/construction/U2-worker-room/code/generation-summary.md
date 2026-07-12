# U2 — Worker modo room · Generation Summary (Ciclo 4)

> Migración del worker `console` → `start` (room). Cambios mínimos: el patrón `AgentServer` +
> `cli.run_app` ya soportaba `start`; el grueso del entrypoint no se tocó.

## Archivo modificado
- **`lk/agent.py`** (única modificación de U2):
  1. **Docstring** — documentados los dos modos de transporte (ROOM default vs CONSOLE fallback), cómo se
     corre cada uno y que en room el wake va al cliente.
  2. **`_CONSOLE_MODE = "console" in sys.argv`** — detección de modo por el subcomando de lanzamiento.
  3. **Wake server-side gateado a console** — `if _WAKE_ENABLED and _CONSOLE_MODE:` arranca el
     `WakeWordDetector` (mic local). En room el worker es headless → `elif _WAKE_ENABLED:` solo loguea que el
     wake corre en el cliente (U4). Evita abrir un mic local inexistente en el worker.
  4. **Log de transporte** al arrancar (`console (audio local)` / `room (track del browser)`).

## Lo que NO se tocó (conservado intacto)
- `ClaudeCodeLLM` (turn handler), `claude_llm.py`, Deepgram STT/TTS, Silero VAD, BVC, prewarm, orbe.
- Socket `LK_CTL_SOCK` + Win+Z (`_press`/`_say`/`stage`), máquina de fases (`_on_user_state`/`_on_agent_state`).
- `claude_daemon` (cerebro caliente).

## Por qué resuelve el buffer del Ciclo 3 (sin tocar buffers)
En room, `voice/room_io/_input.py:153-156` descarta los frames cuando el stream está detached
(`if not self._attached: continue`). `set_audio_enabled(False)` detacha el track del browser → no se acumula
backlog. Es el mecanismo nativo del transporte room; el modo console no lo tenía (mic siempre capturando).

## Verificación
| Check | Resultado |
|---|---|
| `py_compile lk/agent.py` | ✅ |
| `lk/agent.py start` registra worker | ✅ `starting worker` → `registered worker` (url ws://127.0.0.1:7880), espera dispatch |
| Sin client = sin dispatch = sin claude spawneado | ✅ (drenado al timeout, exit 124 = kill nuestro) |
| `console` sigue intacto | ✅ py_compile (no corrible headless sin device de audio; cambio trivial+gateado) |

## Pendiente para el flujo end-to-end (otras unidades)
- **U3** (cliente browser publica/recibe audio) — sin esto no hay track de mic que el worker reciba.
- **U4** (wake en el cliente) — reemplaza el wake server-side en room.
- **Build&Test** del ciclo — valida el turno completo de voz + benchmark de latencia (NFR gate).

## Cómo se corre (room)
```bash
.venv/bin/python lk/agent.py start    # lee LIVEKIT_URL/API_KEY/API_SECRET de .env.local (cargadas por config)
```
(U6/saga-ctl orquestará esto + server + daemon + orb_server + browser.)
