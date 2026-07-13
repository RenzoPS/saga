# Units of Work — Ciclo 9 (Security + Testing)

**Rama**: `feature/security-testing-workflow`
**Estrategia de merge** (Q1=A): **un PR por unidad**. U1 → merge → U2 → merge → U3 → merge. Cada unidad se valida en vivo y entra sola. Si U3 no pasa el gate de latencia, U1 y U2 ya están seguros en `main`.

**Alcance de la defensa** (aclarado por el usuario): contra **lo destructivo obvio** (accidentes, mishears, catástrofes). **NO** contra órdenes legítimas — si Renzo pide algo destructivo y saga tiene el tool, saga lo ejecuta. La garantía de que la orden es auténtica vive en la detección de voz + wake, y se endurece en el Ciclo 6 (speaker verification, diferido). Fuera de scope acá.

---

## U1 — Red de tests + CI

**Objetivo**: construir la red que atrapa las regresiones de U2 y U3. **No toca runtime.**

**Riesgo**: Bajo. No modifica una sola línea de código de producción.

**Archivos**:
- `tests/test_pure.py` (extender), `tests/test_property.py` (NUEVO, PBT), `tests/test_orb_server.py` (NUEVO), `tests/test_config.py` (NUEVO)
- `.github/workflows/tests.yml` (extender)
- `pyproject.toml` (deps de test)

**Contenido**:
- **PBT-09**: adoptar **Hypothesis** como framework PBT. Declararlo en las deps y en las decisiones de tech stack (se formaliza en NFR Requirements).
- **PBT-02 (round-trip)**: base64 del socket de control (`orb_server._forward_ctl` ↔ el parser del agente); serialización del `.saga-settings.json`.
- **PBT-03 (invariantes)**: `normalize_state` siempre devuelve un estado válido del orbe, para cualquier input; el parser de la blacklist JSON nunca crashea (degrada a `[]`) ante JSON arbitrario; **la denylist del guard no deja pasar comandos catastróficos generados adversarialmente**.
- **PBT-04 (idempotencia)**: `_ensure_saga_settings()` aplicado dos veces = una vez.
- **Tests example-based** (Q2=A — solo la superficie de seguridad): `orb_server` (routing, auth, rechazo de CORS, validación), `vc/config.py` (construcción de flags según env, parser de blacklist, settings), `vc/guard.py` (ampliar los casos existentes).
- **CI** (Q3=C): `ruff` en todo el repo + `mypy` **solo** sobre los 3 módulos de seguridad (`vc/guard.py`, `vc/config.py`, `orb/orb_server.py`) + `pip-audit` (SECURITY-10) + seed logging de Hypothesis (PBT-08).

**Criterios de aceptación**:
- Suite verde (example + PBT) en local y en CI.
- CI falla si hay un CVE conocido en una dep (`pip-audit`).
- Las propiedades PBT declaradas en Functional Design están todas implementadas (PBT-01 → PBT-10).
- Cero cambios en el comportamiento en runtime (verificable: el diff no toca `vc/`, `lk/`, `orb/*.py` salvo tests).

**Deuda declarada** (Q2=A): `lk/agent.py`, `lk/wakeword.py`, `lk/claude_llm.py`, `claude_daemon.py`, `vcctl.py`, `vc/claudecli.py`, `vc/runtime.py` quedan sin tests. Requieren mocks pesados de LiveKit/audio/subprocess: es un ciclo aparte, y no aporta a la seguridad. Se registra en `docs/tech-debt-plan.md`.

---

## U2 — Hardening de `orb_server`

**Objetivo**: cerrar la superficie HTTP local. Hoy es el agujero más directo: sin auth, `POST /say` inyecta un turno que llega a Claude.

**Riesgo**: Medio. Superficie acotada y bien entendida, **pero con un punto de coordinación crítico**.

**Archivos**: `orb/orb_server.py`, `orb/orb.html` (cliente), `vc/config.py` (generación del token).

**Contenido** (FR3):
- **FR3.1** — Auth por default: `ORB_TOKEN` se **genera automáticamente** si no existe. No puede quedar vacío = sin auth. Deny-by-default (SECURITY-08).
- **FR3.2** — Eliminar `Access-Control-Allow-Origin: *`; validar `Origin`/`Host` (anti-CSRF, anti-DNS-rebinding).
- **FR3.3** — Headers de seguridad en el HTML servido: CSP, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` (SECURITY-04).
- **FR3.4** — Validación de inputs: `identity`/`room` del `/token` (charset + largo); límite de `Content-Length` en `/attach` y `/say` (SECURITY-05).
- **FR3.5** — TTL corto explícito en el JWT de LiveKit.
- **FR3.6** — Rate limiting básico en `/say` (dispara un turno LLM completo = trabajo caro).

**⚠️ PUNTO DE COORDINACIÓN OBLIGATORIO**: si `orb_server` exige token, **`orb.html` debe mandarlo**. Si esto se rompe, **el orbe deja de conectar y saga queda muda**. El cambio de servidor y el de cliente son atómicos: se hacen y se validan juntos.

**Criterios de aceptación**:
- Un `POST /say` **sin token** devuelve 403 (verificado por test).
- Un `POST` con `Origin` de otro sitio se rechaza (verificado por test).
- El orbe **conecta y funciona en vivo** (Win+Z → turno completo → voz). Sin esto, no se mergea.
- Latencia del turno: sin cambio (estos controles no están en el hot path del LLM).

---

## U3 — Modelo de permisos

**Objetivo**: sacar a saga del god-mode sin que se sienta más lenta ni pierda utilidad.

**Riesgo**: **ALTO**. Es el cambio que puede romper el flujo de voz y el que carga el riesgo de latencia (NFR1).

**Archivos**: `vc/config.py` (flags + settings + system prompt), `vc/guard.py` (fail-closed).

**Contenido** (FR2):
- **FR2.1** — Eliminar `--dangerously-skip-permissions` → **`--permission-mode auto`**. Sin toggle de apagado (NFR3): `VOICE_CLAUDE_SAFE` se elimina.
- **FR2.2** — Guard **fail-open → fail-closed** (SECURITY-15): input no parseable = denegar, no permitir.
- **FR2.3** — **NO** se construye denylist de tools MCP (decisión del usuario, Q4=C). El guard sigue acotado a Bash. La cobertura de MCP la da el clasificador nativo de `auto` + las reglas de FR2.4.
- **FR2.4** — Reglas `permissions.deny` declarativas en `.saga-settings.json` para lo catastrófico/irreversible. Se respetan **incluso en `auto`** (verificado en la doc) y **no cuestan latencia** (son reglas, no clasificación).
- **FR2.5** — Regla **anti-interactivo** en `CLAUDE_SYSTEM_PROMPT`: saga nunca ejecuta comandos que esperen input o abran una TUI (editores, pagers, confirmaciones); siempre flags no interactivos. Un comando interactivo cuelga el turno igual que un prompt de permiso, y hoy no hay nada que lo impida.
- **FR2.6** — **Validación hablada antes de acciones destructivas/irreversibles**, en el `CLAUDE_SYSTEM_PROMPT`. Hoy el prompt (`vc/config.py:168-188`) **no tiene una sola línea de seguridad**: es puro estilo, y encima le dice *"HACELA con la tool y después confirmá corto"* + *"No digas 'no puedo' si tenés cómo hacerlo"* → es acelerador sin freno. La validación por voz **no cuelga el turno** (es diálogo, no stdin) y **cuesta cero latencia** (vive en el prompt). **NO impide** la acción: la confirma. **Riesgo de diseño = exceso de fricción**: si saga pide permiso para todo, se vuelve inusable. Calibración fina en el Functional Design de U3; se valida en vivo.

**Criterios de aceptación** (los más duros del ciclo):
- **G1 — Latencia NO DETECTABLE**: benchmark A/B contra el baseline (turno actual, `CLAUDE_PLUGINS=0`) **+ validación perceptual del usuario** ("¿se siente igual?"). Si el clasificador de `auto` se nota → **plan B: `dontAsk` + allowlist**.
- **G2 — saga sigue siendo útil**: no rechaza acciones legítimas. Si `auto` bloquea de más, el ciclo lo reporta y se replantea.
- Guard fail-closed verificado por test (input basura → deny).
- Flujo de voz completo en vivo: Win+Z, wake, turno, cancel.
- Verificar el manejo del **abort de sesión** (con `-p`, 3 bloqueos seguidos / 20 totales abortan): el daemon respawnea con `--resume` (contexto intacto) y el turno no queda colgado.

---

## Mapa FR → Unidad (trazabilidad; reemplaza al story-map — este ciclo no tiene user stories)

| FR / NFR | Descripción | Unidad |
|---|---|---|
| FR1.1 | Informe de auditoría | Transversal (ya escrito en requirements §3; se consolida al cierre) |
| FR2.1 | `--permission-mode auto` | **U3** |
| FR2.2 | Guard fail-closed | **U3** |
| FR2.3 | Sin denylist MCP (delegado a `auto`) | **U3** |
| FR2.4 | Reglas `permissions.deny` declarativas | **U3** |
| FR2.5 | System prompt anti-interactivo | **U3** |
| FR2.6 | System prompt: validación hablada ante lo destructivo | **U3** |
| FR3.1 | Auth por default en `orb_server` | **U2** |
| FR3.2 | CORS + validación de `Origin`/`Host` | **U2** |
| FR3.3 | Headers de seguridad HTTP | **U2** |
| FR3.4 | Validación de inputs + límites de tamaño | **U2** |
| FR3.5 | TTL del JWT | **U2** |
| FR3.6 | Rate limiting en `/say` | **U2** |
| FR4.1 | `pip-audit` en CI | **U1** |
| FR4.2 | SBOM / Dependabot (evaluar) | **U1** |
| FR5.1 | Hypothesis (PBT-09) | **U1** |
| FR5.2 | PBT round-trip | **U1** |
| FR5.3 | PBT invariantes | **U1** |
| FR5.4 | PBT idempotencia | **U1** |
| FR5.5 | Tests example-based (superficie de seguridad) | **U1** |
| FR5.6 | CI endurecido (lint, typecheck, seed) | **U1** |
| NFR1 | Latencia no detectable | Gate de **U3** (medido en Build & Test) |
| NFR2 | No regresión funcional | Gate de **U2** y **U3** |
| NFR3 | Seguridad incondicional (sin toggle) | **U3** (y transversal) |
| NFR4 | Fail-closed | **U3** |
| NFR5 | Defensa en profundidad | Transversal (U2 + U3) |

**Validación**: los 20 FR y los 5 NFR están asignados. **Cero FR huérfanos.**
