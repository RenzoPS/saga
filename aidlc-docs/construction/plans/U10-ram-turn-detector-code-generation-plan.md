# U10 — RAM del turn detector · Code Generation Plan

## Objetivo
Liberar los ~1.8 GB del turn detector semántico (`MultilingualModel`) cambiando el cierre de turno a
**VAD puro** (silero, ya cargado), con ~3s de silencio. Bajo riesgo: hoy `turn_handling` ya corre VAD +
semántico en paralelo y, según el usuario, el cierre suele darse por silencio igual.

## Decisión (Requirements U10, respondido)
- Q1=C: prioridad baja, pero vale chequearlo. Q2=B: probar en vivo; ~3s sin voz alcanza. Q3=B: VAD puro
  directo (NO STT endpointing). Q4=B: turn detector + relevamiento de qué más pesa.

## Research (Functional Design, confirmado contra livekit-agents 1.6 instalado)
- `TurnDetectionMode = Literal['stt','vad','realtime_llm','manual'] | _TurnDetector`. `"vad"` es válido.
- La RAM la ocupa la **instanciación** `MultilingualModel()` (`agent.py:150`), no el import. Sacarla libera.
- Cierre por silencio con VAD puro = `endpointing.min_delay`. Hoy `2.0` → `3.0` (los "3s" del usuario).
- `preemptive_generation: False` ya está y se mantiene.

## Pasos
- [x] **Step 0 — Baseline + relevamiento (Q4)**: con saga corriendo, medir RAM por proceso (RSS). Registrar
      el turn detector (~1.8 GB) y qué más pesa (worker base, server, orb, daemon). Da el "antes" y el mapa RAM.
- [x] **Step 1 — Cambio en `agent.py`** (3 toques, mínimos):
      1. `turn_handling["turn_detection"]`: `MultilingualModel()` → `"vad"`.
      2. `endpointing.min_delay`: `2.0` → `3.0` (max_delay queda 6.0).
      3. Sacar el import `from livekit.plugins.turn_detector.multilingual import MultilingualModel` (línea 45)
         y actualizar los comentarios (hoy describen "EOU semántico / anti-chopping" → pasa a VAD puro 3s).
- [x] **Step 2 — Verificación estática**: `py_compile` + import del paquete + `tests.test_pure` 11/11.
- [x] **Step 3 — Medición en vivo (usuario, GATE)**: relanzar saga, medir RAM después (esperado: −~1.8 GB).
      Probar que el turno **cierra bien a ~3s** sin cortar a mitad de frase. Criterio de éxito: RAM cae fuerte
      Y la UX de turno se mantiene aceptable. Si corta de más / molesta → ajustar `min_delay` o revertir.
- [x] **Step 4 — Docs + cierre**: si pasa, actualizar `turn-flow.md` / `lk/README` / `operations.md`
      (turn_handling = VAD puro 3s, ya no semántico) + state + audit. Commit + PR (con OK del usuario).

## Trade-off (declarado)
- Se pierde el cierre por SENTIDO. Con VAD puro, una pausa larga (>3s) a mitad de frase puede cerrar el turno
  y mandar incompleto. Mitigación: min_delay 3.0 (margen amplio) + Win+Z corta manual igual. El usuario
  validó que en la práctica ya cerraba por silencio → degradación esperada baja. Step 3 es el gate real.
- Reversible 100%: volver a `MultilingualModel()` + min_delay 2.0 restaura lo de hoy.

## Fuera de scope
- Otros consumos de RAM que el relevamiento (Step 0) marque como grandes → se evalúan aparte, no se tocan en U10.
