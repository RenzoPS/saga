"""Cap de threads de ONNX Runtime para el worker de voz (modo room).

Causa raíz (medida): ONNX Runtime, por default (`intra_op_num_threads=0`), crea threads
igual al número de cores físicos y los hace SPIN (busy-wait) entre inferencias. El wake
"hey saga" (modelo 169 KB, infiere ~cada 240ms) deja esos threads girando en vacío ->
~367% CPU en idle SIN computar casi nada. Medido: worker a ~410% CPU total, el wake solo
a 367% con 50 threads.

Fix confirmado contra docs oficiales (onnxruntime threading.html) + el entorno:
  - onnxruntime 1.26.0 NO trae OpenMP -> `OMP_NUM_THREADS` es inerte. Única vía = SessionOptions.
  - `intra_op_num_threads=1` -> 1 thread en vez de #cores.
  - `session.intra_op.allow_spinning=0` -> el thread DUERME entre inferencias (mata el CPU idle).
Doc: https://onnxruntime.ai/docs/performance/tune-performance/threading.html

`livekit.wakeword` (y los plugins silero / turn_detector) crean `InferenceSession` SIN exponer
`sess_options` (`livekit/wakeword/inference/model.py:87`) -> se inyecta por monkeypatch global
del constructor. Para modelos de audio chicos en tiempo real, 1 thread sin spin es lo correcto.
"""

import onnxruntime as ort

from vc.runtime import log

_PATCHED = False


def cap_onnx_threads(intra: int = 1, inter: int = 1) -> None:
    """Parchea `ort.InferenceSession` para que, cuando el caller NO pase `sess_options`,
    use `intra`/`inter` threads y SIN spinning. Idempotente. Respeta el `sess_options`
    explícito del caller (no lo pisa). Degradación segura: si algo falla al armar las
    opciones, cae al comportamiento default (lo que hay hoy), no rompe el arranque.

    Llamar a NIVEL MÓDULO en el worker, ANTES de cargar cualquier modelo ONNX
    (silero VAD / turn detector / wake)."""
    global _PATCHED
    if _PATCHED:
        return
    _orig = ort.InferenceSession

    def _make_opts() -> "ort.SessionOptions":
        so = ort.SessionOptions()
        so.intra_op_num_threads = intra
        so.inter_op_num_threads = inter
        # spinning OFF: sin esto los threads hacen busy-wait entre inferencias -> CPU en idle.
        so.add_session_config_entry("session.intra_op.allow_spinning", "0")
        so.add_session_config_entry("session.inter_op.allow_spinning", "0")
        return so

    def _patched(path_or_bytes, *args, sess_options=None, **kwargs):
        if sess_options is None and "sess_options" not in kwargs:
            try:
                sess_options = _make_opts()
            except Exception as e:  # degradación segura: default de ONNX
                log(f"[onnx] no pude armar SessionOptions, uso default: {e}")
        return _orig(path_or_bytes, *args, sess_options=sess_options, **kwargs)

    ort.InferenceSession = _patched
    _PATCHED = True
    log(f"[onnx] threads capados a intra={intra}/inter={inter}, spinning OFF")
