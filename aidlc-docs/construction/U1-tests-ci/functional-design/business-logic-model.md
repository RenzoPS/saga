# Business Logic Model — U1 (Red de tests + CI)

> U1 no agrega lógica de negocio: **construye la red que verifica la que ya existe**. Este documento modela el comportamiento de las funciones bajo test (el "dominio" de la unidad) y la arquitectura de la suite.

---

## 1. Superficie bajo test

| Módulo | Funciones | Propiedades | ¿Por qué está en U1? |
|---|---|---|---|
| `orb/orb_server.py` | `normalize_state`, routing, `_authorized`, `_serve_token`, `_forward_ctl` | P1, P2, P3, P4 | Superficie que **U2 va a modificar**. Sin tests acá, U2 se hace a ciegas. |
| `vc/config.py` | `_read_plugins_blacklist`, `_ensure_saga_settings`, `build_claude_base_args` | P5, P6 | Superficie que **U3 va a modificar**. Corre en el arranque: si falla, saga no levanta. |
| `vc/guard.py` | `denied` | P7, P8 | El control de seguridad central. **U3 lo va a endurecer** con los bypasses que P7 encuentre. |
| `vc/attach.py` | `stage_text`, `clear_text`, `has_staged`, `take_staged` | P9 | Único componente con estado mutable. Ya tiene tests de ejemplo; le falta el stateful PBT. |
| `vc/session.py` | `is_reset_command`, `is_visual_command` | P10 | Funciones puras ya testeadas por ejemplo; se les agrega robustez. |

**Fuera de U1** (deuda declarada, Q2=A del Units Generation): `lk/agent.py`, `lk/wakeword.py`, `lk/claude_llm.py`, `claude_daemon.py`, `vcctl.py`, `vc/claudecli.py`, `vc/runtime.py`. Requieren mocks pesados de LiveKit, audio y subprocess. No aportan a la seguridad y convertirían el ciclo de seguridad en un ciclo de cobertura.

---

## 2. Comportamiento modelado

### 2.1 `normalize_state` — colapso a un estado seguro
Función total: todo input cae en alguno de los 10 estados válidos, y el fallback es `idle`. No hay input que la rompa ni que produzca un estado fuera del conjunto. `idle` actúa como **elemento absorbente**: es el default, el fallback del input inválido, y el destino del watchdog cuando el orbe queda colgado más de 180s.

### 2.2 Socket de control — transporte con framing por línea
`orb_server` recibe un POST del browser, codifica el body en base64 y lo escribe en el socket Unix del agente como `<verbo> <payload>\n`. El agente lee con `readline()`. **Dos propiedades sostienen este diseño**: el round-trip debe preservar el contenido (P3) y el payload **nunca** debe contener el delimitador (P4). La segunda es una propiedad de seguridad: sin ella, el framing es inyectable.

### 2.3 Parser de la blacklist — degradación segura
Corre en el **arranque**. Su contrato es "nunca romper": ante cualquier basura devuelve `[]` y saga levanta sin plugins deshabilitados. Un crash acá = saga no arranca. Esto lo hace un caso de libro para PBT: la propiedad no es "parsea bien", es "**nunca lanza**".

### 2.4 Guard — denylist de patrones (con límite conocido)
Función pura `denied(cmd) -> str | None`. Recorre 15 regex; devuelve la etiqueta del primero que matchea. **Límite estructural conocido y aceptado**: una denylist de regex es evadible por construcción. El PBT no la va a "certificar" — la va a **auditar**, buscando bypasses (P7) y falsos positivos (P8). Lo que encuentre es material para U3.

### 2.5 Attach — máquina de estados de un solo slot
El texto vive en memoria del agente; la imagen, en `/tmp`. Consume-once en el texto. Sin locks: todo corre en el hilo del event loop del agente. Es el único componente con estado mutable de U1 → único candidato a **stateful PBT** (PBT-06).

---

## 3. Arquitectura de la suite (decisión Q1=B: pytest)

```
tests/
├── test_pure.py           # EXISTENTE (11 tests de ejemplo) — se conserva, pytest lo corre sin tocarlo
├── generators.py          # NUEVO — generadores de dominio reutilizables (PBT-07)
├── test_properties.py     # NUEVO — los PBT (P1..P10)
├── test_orb_server.py     # NUEVO — tests de ejemplo: routing, auth, CORS, token, validación
└── test_config.py         # NUEVO — tests de ejemplo: flags según env, parser, settings
```

**Por qué pytest** (Q1=B): Hypothesis entra como dependencia de test igual, así que el argumento "stdlib-only" del CI se cae solo. pytest corre los `unittest.TestCase` existentes **sin modificarlos**, así que la migración no rompe nada. Y los tests de `orb_server` (levantar el server en un puerto libre, tumbarlo, testear rechazos) son mucho más limpios con fixtures.

**Generadores centralizados** (PBT-07): `generators.py` es un módulo único y reutilizable. Prohibido duplicar generadores entre archivos de test.

---

## 4. CI (decisiones Q2=C)

Pipeline (`.github/workflows/tests.yml`), en orden:

1. **`py_compile`** — sintaxis de todo el repo (ya existe, se conserva).
2. **`ruff`** — lint de todo el repo.
3. **`mypy`** — typecheck **solo** de `vc/guard.py`, `vc/config.py`, `orb/orb_server.py` (los 3 módulos de seguridad; el resto del repo no tiene anotaciones sistemáticas y sería un refactor aparte).
4. **`pytest`** — suite completa (ejemplos + PBT), con la **seed de Hypothesis logueada** (PBT-08) para poder reproducir cualquier fallo.
5. **`pip-audit`** — escaneo de CVEs (SECURITY-10). **Bloqueante con allowlist** (Q2=C): falla el build por default, pero se pueden marcar CVEs específicos como aceptados, con su justificación en un archivo versionado.

**Por qué la allowlist** (Q2=C): un CVE en una dependencia **transitiva** (livekit, onnxruntime, faster-whisper arrastran árboles grandes) puede no tener patch disponible. Sin allowlist, el CI queda rojo y bloqueado sin que haya nada que hacer — y un CI que está siempre rojo deja de leerse, que es peor que no tenerlo.

---

## 5. Flujo del hallazgo del guard (decisión Q3=A)

```
P7 (PBT del guard) corre
        │
        ├─ encuentra bypasses (ESPERADO: p.ej. "rm -r -f")
        │        │
        │        ├─→ se REGISTRAN en el reporte de U1 (lista concreta y medida)
        │        ├─→ el test queda como expected-failure DOCUMENTADO (U1 cierra en verde)
        │        └─→ cada bypass se vuelve test de regresión permanente (PBT-10)
        │
        └─→ U3 endurece el guard (FR2.2/FR2.4) SABIENDO QUÉ CERRAR
                 └─→ al cerrar, los expected-failure pasan a verde
```

**Por qué así**: mantiene los límites de las unidades (el guard es U3) y hace que U3 llegue con evidencia medida en vez de endurecer a ciegas. Es exactamente el flujo que PBT-10 prescribe: el contraejemplo que encuentra la propiedad se convierte en regresión permanente.

---

## 6. Restricción transversal

**U1 no toca una sola línea de código de producción.** Verificable de forma objetiva: el diff de U1 no debe modificar nada bajo `vc/`, `lk/`, `orb/*.py` (solo `tests/`, `.github/`, `pyproject.toml`). Es lo que la vuelve una unidad de riesgo bajo y la razón por la que va primera.
