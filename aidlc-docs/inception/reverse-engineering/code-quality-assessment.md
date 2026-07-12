# Code Quality Assessment

> Refresh 2026-07-12 (estado post-U7–U11, room-only). Reemplaza la versión 2026-06-21, que evaluaba
> el sistema viejo (flujo clásico/console + helpers de TTS propios, todo eliminado en U7).

## Test Coverage

- **Overall**: Fair (focalizada, por diseño). Solo se testean **funciones puras** del paquete
  `vc/` (sin audio/red/subprocess): el flujo de audio/Win+Z/threads/signals no se puede
  runtime-testear sin mic ni subprocess. Cobertura acotada pero bien elegida.
- **Unit Tests**: `tests/test_pure.py` (unittest, **3 clases / 11 métodos**):
  `TestSessionKeywords` (`is_reset_command`, `is_visual_command` con word boundaries),
  `TestGuardDenylist` (`denied` — bloquea rm -rf/dd/mkfs/git --force/curl|sh, permite lo normal),
  `TestAttach` (adjunto consume-once: staging de texto en memoria, imagen que borra el worker,
  no `take_staged`). Cubren la lógica de decisión con casos borde. **Ya NO hay tests de TTS**
  (`clean_for_tts`/chunking/flush se fueron con `vc/tts.py` en U7; el TTS lo maneja el pipeline
  de LiveKit).
- **Integration Tests**: No (intencional). La verificación de integración es **manual en vivo**
  (Win+Z), documentada en `.claude/CLAUDE.md`. Hay git baseline para rollback.
- **CI**: `.github/workflows/tests.yml` (push/PR a `main`, Python 3.12) corre dos gates
  **stdlib-only (no instala deps)**: `py_compile` de TODO el repo (`git ls-files '*.py'`) para
  atrapar errores de sintaxis, y `unittest tests.test_pure`. Es un smoke real, no cobertura.

## Code Quality Indicators

- **Linting**: No configurado (sin ruff/flake8/`.editorconfig`/pre-commit en el repo).
- **Type checking**: No (mypy ausente). Hay type hints parciales, algunos como strings
  (`"subprocess.Popen | None"`) por compat de versiones, sin checker que los valide.
- **Code Style**: Consistente y de alta calidad. Convenciones uniformes: docstrings de módulo
  que explican el **por qué** (no solo el qué), nombres en español, separadores de sección,
  y comentarios "leídos con sangre" que anotan la causa raíz de cada gotcha no obvio
  (spinning de ONNX, `bool("0") is True`, plugins en el main thread, `activation_threshold 0.7`,
  `load_fnc=0`, params de turno top-level deprecados vs `turn_handling`).
- **Documentation**: Excelente — lo más fuerte del repo. `README.md`, `.claude/CLAUDE.md`,
  `lk/README.md`, `docs/` (architecture/turn-flow/operations/code-guide) y los artefactos de
  reverse-engineering en `aidlc-docs/`. El conocimiento operativo (gotchas de LiveKit, WebRTC,
  latencia, RAM) está capturado por escrito y actualizado por ciclo (U7–U11).

## Technical Debt

- **Bug TTS Deepgram en modo agéntico** (funcional, el principal): respuestas largas que usan
  tools tardan 13-17s+ y el TTS de Deepgram corta/timeoutea antes de terminar de hablar. Deuda
  abierta conocida; el watchdog `_busy` se subió a 60s como paliativo (`lk/agent.py`), pero no
  resuelve el corte del stream de audio.
- **Maquinaria de cancelación/streamer vestigial (U7.3)**: `vc/runtime.py` mantiene
  `cancel_handler` (SIGUSR2), `set_current_streamer`/`cancel_streamer` y `kill_current_proc`
  sin callers vivos en el flujo room — restos del camino one-shot/clásico. La cancelación real en
  room va por el flag `_cancel` (seteado en `lk/claude_llm.py`, chequeado en `vc/claudecli.py`) +
  `session.interrupt(force=True)` (`lk/agent.py`). `set_current_proc` solo lo usa el fallback
  one-shot (`vc/claudecli.py`). El acoplamiento al patrón claudecli confunde sobre qué ruta de
  cancel está activa; el streamer TTS ya no aplica.
- **Shutdown del executor del wake**: el `WakeWordTrackDetector` corre `predict` en
  `run_in_executor` dentro del event loop del agente (`lk/wakeword.py`) y al bajar cancela su
  task/cierra el stream; el teardown puede dejar ruido/traza en el shutdown. Bajo impacto
  (wake es opt-in), pero es cabo suelto conocido.
- **Recall del wake marginal en voz rioplatense**: el modelo "hey saga" rinde recall ~0.06-0.13
  sobre voz rioplatense → wake poco fiable como está. Mitigado porque es **opt-in**
  (`SAGA_WAKE_ENABLED=1`, default off) y el trigger real es Win+Z.
- **Deps declaradas pero muertas/inertes**: `livekit-plugins-turn-detector` quedó sin cargar tras
  U10 (VAD puro) — candidato a remover; `livekit-plugins-noise-cancellation` (BVC) es inerte en
  self-hosted (requiere LiveKit Cloud); `vosk`/`sounddevice`/`wake_daemon.py` duermen fuera de scope.
- **LiveKit sin pin en `pyproject.toml`**: la reproducibilidad depende del lock
  (`requirements.txt`); un `pip install` fresco sin lock puede traer una API incompatible (drift ya
  sufrido en la migración a `AgentServer`/auto-dispatch).
- **Acoplamiento fuerte al entorno** (Arch + Hyprland + Wayland + binarios `claude`,
  `livekit-server`, `grim`, `hyprctl`, `mpg123`): no portable; aceptable por ser herramienta
  personal single-user.
- **Restos citados que ya no existen**: `is_goodbye` fue removido pero seguía nombrado en artefactos
  de documentación; limpieza aplicada en este refresh.

## Patterns and Anti-patterns

### Good Patterns
- **Degradación elegante en cascada**: Deepgram→whisper/edge, daemon→one-shot, guard fail-open,
  `dotenv` degrada en silencio si falta, `onnx_tune` cae al default de ONNX si falla armar opciones,
  blacklist de plugins degrada a `[]` ante JSON inválido, `_ensure_saga_settings` degrada a None.
  El sistema "nunca queda mudo" y "no rompe el arranque".
- **Verificación de API contra la lib/versión instalada** (anti cargo-cult): las decisiones citan
  la doc real — `onnxruntime 1.26.0` no trae OpenMP → única vía es `SessionOptions`
  (`lk/onnx_tune.py`); toda la config de turnos va en `turn_handling` porque los params top-level
  están deprecados; `enabledPlugins:false` verificado contra `claude mcp list`. Se comprueba,
  no se asume.
- **Reversibilidad por toggles**: `CLAUDE_PLUGINS` (default off, blacklist en archivo editable
  `configs/plugins-blacklist.json`), `SAGA_WAKE_ENABLED` (off), `VOICE_CLAUDE_SAFE`,
  `VOICE_CLAUDE_MEM` — todos con default seguro y comparación del valor real (evitan el
  `bool("0") is True`). Cambios mínimos y revertibles.
- **Fuente única de configuración** (`vc/config.py`): paths, flags, voces, system prompt, regex,
  args de Claude, sockets, blacklist — evita el drift entre daemon y fallback.
- **Seguridad pragmática**: sockets y archivos sensibles a `0o600` (sin esto = RCE local con
  god-mode), hook `vc/guard.py` (denylist de bash catastrófico, fail-open, **testeado**),
  borrado consume-once de capturas/adjuntos (privacidad), secretos en `.env.local` gitignored,
  path-traversal bloqueado en `/vendor`, token `/token` con solo `room_join`.
- **Robustez de procesos**: grupos de proceso (`start_new_session=True`) para matar árboles
  (incluye subspawns de claude-mem) sin huérfanos; PID-files anti-recycle (validan `starttime` de
  `/proc`); `vcctl` mata por ruta exacta leyendo `/proc` (no `pkill -f`, que se auto-mataría);
  server y worker **frescos en cada `start`** (sin rooms/workers zombie); anti doble-arranque por
  probe de socket.
- **Cap de threads ONNX en tiempo real**: monkeypatch **respetuoso** (no pisa el `sess_options`
  explícito del caller), idempotente y con degradación segura — mató el ~367% CPU idle del wake (U9).
- **Separación de canales**: estado del orbe por SSE (canal confiable, cola por cliente), sin
  metering de audio por HTTP (decisión consciente documentada tras fallar el sync).
- **Auto-dispatch nativo** (1 room / 1 agente, U8): elimina el race del `create_dispatch` por API
  (`load_fnc=0`, `drain_timeout=0`, `num_idle_processes=1`, `close_on_disconnect=False`).

### Anti-patterns / olores
- **Bug TTS Deepgram sin resolver** (el principal, funcional): respuestas largas con tools se cortan.
- **Maquinaria de cancel/streamer vestigial** (U7.3): `cancel_handler`/`cancel_streamer`/
  `kill_current_proc` sin callers vivos en room; acopla `vc/runtime.py` al camino one-shot y
  confunde sobre la ruta de cancelación activa.
- **Código/deps muertos**: `turn-detector` y `noise-cancellation` declarados sin uso;
  `vosk`/`sounddevice`/`wake_daemon.py` dormidos.
- **god-mode por default** (`--dangerously-skip-permissions` ON): superficie de riesgo inherente
  (voz + ejecución sin permisos), mitigada por el guard fail-open y documentada.
- **Monkeypatch global de `InferenceSession`**: necesario (los plugins no exponen `sess_options`),
  pero es un parche a nivel proceso, frágil ante cambios internos de la lib.
- **Wake poco fiable en voz rioplatense** (recall 0.06-0.13): el feature opt-in no rinde como está.
- **Sin tooling automatizado de calidad** (lint/type/coverage): la calidad se sostiene por
  disciplina manual + un CI mínimo (py_compile + unittest); escala mal si crece el equipo.

## Resumen ejecutivo
Código **maduro y muy cuidado para una herramienta personal single-user**, ahora consolidado en un
**modo único (room)** tras eliminar el flujo clásico/console en U7 — lo que borró la mayor deuda de
la versión anterior (la duplicación clásico/LiveKit). Documentación y robustez operativa
sobresalientes, decisiones justificadas **con evidencia contra la doc/versión real**, seguridad
pragmática bien pensada (guard testeado, `0o600`, consume-once, secretos gitignored) y todo
reversible por toggles con defaults seguros. Las deudas **vivas** son concretas: un **bug funcional**
(el TTS de Deepgram se corta en respuestas largas con tools en modo agéntico), **maquinaria de
cancelación/streamer vestigial** del camino one-shot (U7.3), **ruido en el shutdown del executor del
wake**, y un **wake word poco fiable en voz rioplatense** (recall 0.06-0.13, mitigado por ser
opt-in). Deuda estructural menor: **deps declaradas sin uso** (turn-detector, noise-cancellation),
**LiveKit sin pin** (mitigado por el lock), acoplamiento a Arch/Hyprland y ausencia de
lint/typecheck (mitigada por el CI mínimo). Ninguna es bloqueante para el uso single-user actual; el
**bug de TTS** y la **limpieza de la maquinaria U7.3** son los primeros candidatos a atacar.
