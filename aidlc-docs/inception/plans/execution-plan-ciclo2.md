# Execution Plan — Ciclo 2: Wake word "hey saga"

**Generado**: 2026-06-22  
**Tipo**: Feature — Brownfield  
**Alcance**: Integrar livekit-wakeword en el agente LiveKit existente

---

## Detailed Analysis Summary

### Transformation Scope
- **Tipo de cambio**: Feature addition (no refactor, no arquitectura nueva)
- **Archivos a crear**: `lk/wakeword.py`, `scripts/train_wakeword.py`
- **Archivos a modificar**: `lk/agent.py`, `pyproject.toml`, `requirements.txt`
- **Archivos sin tocar**: `vc/`, `orb/`, `vcctl.py`, `claude_daemon.py`, `orb_server.py`

### Change Impact Assessment
- **Runtime**: wake detection corre en background thread/task; no toca el response path de Deepgram+Claude
- **Audio**: livekit-wakeword captura mic en modo local (pre-trigger); nada a la nube
- **Integración**: al detectar "hey saga" → dispara el flujo `press` existente (igual que Win+Z)
- **Toggle**: estado `is_wake_enabled` (False por default); activable por comando o flag

### Risk Assessment
- **Riesgo 1** (MEDIO): livekit-wakeword en español = multilingüe, puede tener más falsos+ que inglés. Mitigación: synthetic augmentation + benchmark en vivo.
- **Riesgo 2** (BAJO): conflicto mic entre LiveKit audio y wake listener. Mitigación: livekit-wakeword está diseñado para coexistir con el agente (es del mismo stack).
- **NFR duro**: latencia Deepgram+Claude NO puede retroceder. Gate: benchmark antes de aprobar Build & Test.

### CORRECCIÓN POST-BUILD&TEST (2026-06-22) — Feedback Loop
Build and Test invalidó "synthetic-only". Diagnóstico verificado en código:
- El modelo synthetic-only (piper FPPH 54; VoxCPM scores reales 0.6-0.88) NO discrimina voz real de ruido.
- **Causa raíz**: el training corrió con `--skip-acav` → sin los negativos reales ACAV100M (2000h).
  El batch espera 1024 ACAV100M-samples/batch (`livekit/wakeword/config.py:152`); sin ellos no hay
  "general negative speech data" y la propia librería advierte "high false positive rate"
  (`livekit/wakeword/training/trainer.py:113-117`).
- **Research cross-speaker**: Alexa / openWakeWord pre-trained funcionan por ~31k horas de NEGATIVOS
  reales. El gap NO era el TTS ni el threshold — eran los negativos reales.
- **Decisión corregida**: Training = synthetic positives (VoxCPM) **+ ACAV100M real negatives (2000h, ~16GB
  features pre-computadas)**. `setup` SIN `--skip-acav`. El trainer carga ACAV automáticamente si el
  `.npy` está en `data_dir/features/`.
- **Probabilidad de éxito cross-speaker**: ~65-75% (vs ~20% synthetic-only). Techo sin grabar voces reales.

---

## Phases to Execute

### INCEPTION PHASE (Ciclo 2)
- [x] Workspace Detection — reutilizado de Ciclo 1
- [x] Reverse Engineering — reutilizado de Ciclo 1 (brownfield vigente)
- [x] Requirements Analysis — COMPLETO (Q2=B, Q3=A, Q4=A, Q5=B)
- [x] User Stories — SKIP (feature sin ambigüedad de scope)
- [ ] Workflow Planning — **EN CURSO** (este documento)
- [x] Application Design — SKIP (sin servicios/componentes nuevos)
- [x] Units Generation — SKIP (entregable único)

### CONSTRUCTION PHASE (Ciclo 2)
- [x] Functional Design — **SKIP** — *Rationale*: la lógica es un hook directo (wake detectado → `press`); toggle = bool; sin modelos, sin reglas complejas, sin estado persistente.
- [x] NFR Requirements — **SKIP** — *Rationale*: extensiones todas opt-out (Security/Resiliency/PBT = No desde Ciclo 1).
- [x] NFR Design — **SKIP**
- [x] Infrastructure Design — **SKIP** — *Rationale*: livekit-wakeword es pip package local + modelo ONNX local; sin cloud, sin DB, sin deployment changes.
- [ ] Code Generation — **EXECUTE**
- [ ] Build and Test — **EXECUTE**

### OPERATIONS PHASE
- [ ] Operations — PLACEHOLDER (fuera de scope)

---

## Code Generation — Entregables

### 1. `lk/wakeword.py` (nuevo)
Módulo que encapsula livekit-wakeword:
- Clase `WakeWordListener` con `start()` / `stop()`
- Callback `on_wake(phrase)` → llama a handler externo
- Toggle state (`enabled` flag, False por default)
- Logging de detecciones + falsos positivos para ajuste de umbral

### 2. `lk/agent.py` (modificar)
- Importar `WakeWordListener` a nivel módulo (mismo patrón que deepgram/silero)
- Instanciar y arrancar el listener en `entry()` si `is_wake_enabled`
- Handler: `on_wake` → simula el flujo `press` (igual que `LK_CTL_SOCK` press)
- Flag de toggle: leer de env o argumento (default off)

### 3. `scripts/train_wakeword.py` (nuevo)
- Generar synthetic positives para "hey saga" con VoxCPM (34 voces diversas)
- **Negativos reales ACAV100M (2000h)**: `setup` SIN `--skip-acav` baja el `.npy` (~16GB) a
  `data_dir/features/`; el trainer lo carga automáticamente como clase `ACAV100M_sample`
- Invocar el pipeline de entrenamiento de livekit-wakeword
- Exportar modelo ONNX a `models/hey_saga/hey_saga.onnx`
- Documentar el comando exacto para reproducir

### 5. Beep de feedback (cableado en `lk/wakeword.py`)
- Al disparar el wake → `vc.sound.play_beep()` (reusa el beep existente, sin código nuevo)
- `ensure_beep()` en `start()` genera el WAV una vez

### 4. `pyproject.toml` + `requirements.txt` (modificar)
- Agregar `livekit-wakeword` (sin pin de versión; resolver con pip)

---

## Build and Test — Criterios de aceptación

1. `py_compile lk/wakeword.py lk/agent.py scripts/train_wakeword.py` → sin errores ✅
2. `python -c "from lk.wakeword import WakeWordDetector"` → importa limpio ✅
3. Modelo entrenado existe en `models/hey_saga/hey_saga.onnx`
4. **ACAV100M presente en training**: `data_dir/features/openwakeword_features_ACAV100M_2000_hrs_16bit.npy`
   existe; el log del trainer NO muestra el warning "ACAV100M features not found".
5. **Prueba en vivo** (usuario): decir "hey saga" → saga responde + beep. Cross-speaker: separación
   clara entre score real (alto) y falsos+ (bajo). Win+Z sigue funcionando.
6. **Benchmark de latencia**: respuesta post-wake ≤ latencia actual (~2-3s). Gate duro.

### Historial de iteraciones (Build and Test)
| # | Positivos | Negativos | Resultado |
|---|-----------|-----------|-----------|
| 1 | piper synthetic | sin ACAV (skip) | FPPH 54 — dispara en silencio |
| 2 | VoxCPM synthetic | sin ACAV (skip) | scores reales 0.6-0.88 solapados con falsos+ |
| 3 | VoxCPM synthetic | **ACAV100M 2000h real** | ← approach corregido, pendiente |

---

## Estimated Timeline
- Code Generation: 1 sesión
- Training + benchmark: requiere prueba manual del usuario

---

## Success Criteria
- "hey saga" dispara el agente (toggle ON)
- Win+Z sigue funcionando sin cambios
- Latencia no regresa
- Toggle OFF = comportamiento idéntico al estado actual
