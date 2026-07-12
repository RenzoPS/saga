# U9 — Cap threads ONNX (CPU del wake) · Code Generation Plan

## Objetivo
Bajar el CPU del worker de ~462% (medido, idle) sin sacar ninguna feature. Causa raíz: ONNX
Runtime crea threads = #cores y los hace *spin* (busy-wait) entre inferencias. El wake "hey saga"
(modelo de 169 KB, infiere cada ~240ms) queda con 8 threads girando en vacío → ~390% CPU en idle.

## Causa raíz (confirmada, docs oficiales onnxruntime threading.html + entorno)
- `intra_op_num_threads` default `0` = threads igual a #cores físicos (8).
- Thread **spinning** ON por default → busy-wait entre inferencias = CPU quemado sin computar.
- `onnxruntime 1.26.0` **sin OpenMP** → `OMP_NUM_THREADS` NO tiene efecto. Única vía = `SessionOptions`.
- `livekit.wakeword` crea `ort.InferenceSession(...)` SIN `sess_options` (`inference/model.py:87` +
  feature_extractor) → no se puede configurar por parámetro → monkeypatch.

## Cambio (mínimo, reversible)
Un helper que parchea `ort.InferenceSession` para inyectar, cuando el caller NO pasa `sess_options`:
- `intra_op_num_threads = 1`
- `inter_op_num_threads = 1`
- `add_session_config_entry("session.intra_op.allow_spinning", "0")`

Aplicado en `lk/agent.py` a **nivel módulo, antes** de `from lk.wakeword import ...` y de cargar
silero/turn detector. Idempotente (no re-parchea). Si el caller ya pasa `sess_options`, respeta el suyo.

## Pasos
- [x] **Step 0 — Baseline medido**: con saga corriendo + wake ON, registrar CPU/RAM/threads por proceso
      (worker + inference). Guardar el número de partida (sin esto no hay con qué comparar).
- [x] **Step 1 — Helper de patch**: `lk/onnx_tune.py` (módulo nuevo, chico) con `cap_onnx_threads()`:
      envuelve `ort.InferenceSession` inyectando las SessionOptions de arriba. Idempotente + respeta
      sess_options explícito. Docstring con la causa raíz y el link a la doc.
- [x] **Step 2 — Cablearlo en agent.py**: llamar `cap_onnx_threads()` a nivel módulo, lo más arriba
      posible (antes de los imports que cargan modelos). 1-2 líneas.
- [x] **Step 3 — Verificación estática**: `py_compile` + import del paquete + `tests.test_pure` 11/11.
- [x] **Step 4 — Medición en vivo (usuario)**: relanzar saga, repetir la medición de Step 0, comparar.
      Criterio de éxito: CPU idle del wake cae fuerte (objetivo < 1 core) SIN romper la detección de
      "hey saga" ni Win+Z ni turnos. Si la detección se degrada (falla el wake), revertir.
- [x] **Step 5 — Docs + cierre**: si pasa, anotar el gotcha en docs (operations.md / lk/README) y state.

## Riesgos / trade-offs
- `intra_op=1` para un modelo de 169 KB: esperado neutro o más rápido (menos overhead). Riesgo bajo.
- Monkeypatch global: afecta TODAS las InferenceSession del proceso worker (wake + VAD + turn detector).
  Para modelos chicos de audio en tiempo real es lo correcto, pero hay que VERIFICAR en vivo que el
  turn detector y el VAD sigan andando bien (no solo el wake). Por eso Step 4 es gate del usuario.
- Si la lib `livekit.wakeword`/onnxruntime cambia la firma en un update, el patch podría quedar inerte
  (degradación segura: vuelve al default, no crashea). Documentado.

## Fuera de scope (otros ciclos)
- RAM del turn detector semántico (1.8 GB) → fix C (turn detector → VAD puro). Decisión de UX aparte.
- Split Pi (browser/mic vs worker) + onnxruntime-web para el wake → deploy en hardware chico, futuro.
