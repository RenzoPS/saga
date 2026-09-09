"""Aislamiento de la suite respecto de una instancia de saga corriendo.

`vc.runtime.log()` escribe en `LOG_FILE`, y los tests ejercitan justamente el código que
loguea (turnos, bloques de voz, interrupciones). Si eso apunta al `saga.log` de producción,
correr pytest mientras saga está en una llamada intercala transcripts de fixtures con la
conversación real —"En el principio creó Dios los cielos", "palabra palabra FINAL"— y el
monitor queda ilegible justo cuando lo estás usando. Pasó en vivo.

Esto corre ANTES de que se importe cualquier módulo de test (pytest carga conftest primero),
así que `vc.config` ya lee la variable al importarse.
"""

import os
import tempfile
from pathlib import Path

_LOG_DE_TESTS = Path(tempfile.gettempdir()) / "saga-tests.log"
os.environ.setdefault("SAGA_LOG_FILE", str(_LOG_DE_TESTS))
