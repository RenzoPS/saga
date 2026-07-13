# U2 — NFR Requirements

**Unidad**: U2 — Hardening de `orb_server` · **Stage obligatorio por PBT-09** (selección de la
herramienta de property-based testing)

---

## 1. Tech stack — **sin decisiones nuevas** (heredado de U1)

U1 ya eligió y validó el stack de calidad, y **está en `main`**. U2 **no introduce ninguna
herramienta nueva** (regla del proyecto: no agregar dependencias si el stack existente alcanza):

| Herramienta | Rol | Estado |
|---|---|---|
| **pytest** | runner | En `main` (U1) |
| **Hypothesis** | **PBT (PBT-09)** | En `main` (U1) |
| **ruff** | lint (todo el repo) | En `main` (U1) |
| **mypy** | typecheck (`guard`, `config`, **`orb_server`**) | En `main` (U1) — `orb_server` **ya está** en el scope |
| **pip-audit** | CVEs (bloqueante + allowlist) | En `main` (U1) |

**PBT-09 — cumplido por herencia**: Hypothesis fue elegido en U1 con sus 4 requisitos verificados
(generadores custom, shrinking, seed reproducible, integración con el runner). U2 **usa el mismo**.
No se re-litiga.

**Perfiles de Hypothesis para U2**: las propiedades de U2 son **todas de seguridad** (U2-P1…U2-P6) →
corren con el perfil **`thorough`** (1000+ ejemplos) además del `default` (100) en CI. Es el mismo
criterio que U1 aplicó a P4/P7/P8.

**Dependencia nueva de producción**: **ninguna**. `orb_server` sigue siendo **stdlib + `livekit-api`
lazy en `/token`** — `secrets` y `hmac` son stdlib. **La propiedad "stdlib-only" del módulo se
conserva**, que era una decisión de diseño explícita del proyecto.

---

## 2. NFR1 — Rendimiento (**restricción dura del usuario**: *"el RENDIMIENTO ES CRUCIAL"*)

**Criterio (heredado del ciclo)**: latencia **NO DETECTABLE**. No hay presupuesto en ms que gastar.

### Análisis de impacto (por qué el diseño no puede regresar la latencia)

**El hot path del turno de voz NO pasa por `orb_server`.** El audio va por WebRTC (LiveKit), el LLM
por el socket de control del agente. Lo único que `orb_server` toca en el turno es **`POST /state`**
(una transición del orbe: `rec` → `think` → `speak` → `idle`).

Lo que la puerta agrega **por request**:

| Paso | Costo real |
|---|---|
| `Host` check | un lookup en un `frozenset` |
| Token | un `hmac.compare_digest` sobre 43 chars |
| Límite | un `int()` sobre `Content-Length` |
| Headers | 4 `send_header()` |

→ **Orden de microsegundos.** Contra un turno de voz de ~2.09s (baseline de U1), es **ruido de
medición**.

**`/events` (SSE)**: se autentica **una sola vez**, al abrir la conexión (es long-lived). **No hay
costo por evento.** Esto es deliberado: poner el check por evento habría sido el único diseño capaz
de tocar la latencia.

**Lo que se descartó también protege NFR1**: el rate limit habría metido un lock + un deque en el
path de `/say`; la CSP con nonce, una sustitución de string por cada carga del HTML. Ninguno de los
dos entra.

**Gate de verificación** (Build & Test):
1. **Benchmark A/B**: TTFT antes/después contra el baseline de U1 (**mediana ~2.09s**, modo rápido,
   `CLAUDE_PLUGINS=0`).
2. **Validación perceptual en vivo** del usuario: *"¿se siente igual?"*.
3. **Criterio de fallo**: si se percibe lentitud → **se rediseña o se descarta el control**. No se
   negocia.

---

## 3. NFR2 — No regresión funcional (**el riesgo #1 de esta unidad**)

**Punto de coordinación C1**: `orb.html` ↔ `orb_server` es **atómico**. Si el server exige token y el
cliente no lo manda → **el orbe no conecta y saga queda muda**.

| Riesgo | Mitigación |
|---|---|
| El cliente no manda el token → orbe muerto | Cambio **atómico** (mismo commit) + **validación en vivo obligatoria**: turno de voz completo |
| El `EventSource` no puede mandar headers | **Ya resuelto en el diseño**: `/events` se autentica por `?token=` (BR-1) |
| La CSP rompe el WebRTC | **Ya resuelto en el diseño**: la CSP **no toca** `connect-src` ni `script-src` (BR-10) |
| El `Host` check rechaza al cliente legítimo | La allowlist incluye las 3 formas (`127.0.0.1`, `localhost`, `[::1]`). `vcctl` abre el browser en `127.0.0.1` |
| `vcctl` no pasa el token → orbe muerto al arrancar | El server **autogenera** el token (BR-2) — pero entonces `vcctl` no lo conoce → **`vcctl` es la fuente de verdad** y lo inyecta por env. Se verifica en vivo |

**Criterio de aceptación**: `saga-ctl start` → el orbe conecta → **turno de voz completo** (Win+Z,
voz, respuesta hablada) → sin regresión. **Validado por el usuario en vivo.**

---

## 4. NFR3 — Seguridad incondicional (sin toggle)

Los controles de U2 son **incondicionales**: no hay env var que los apague. `ORB_TOKEN` vacío
**ya no significa** "sin auth" (BR-2) — significa "el server se genera uno".
La reversibilidad la da **git** (la rama), no un flag de producto.

---

## 5. NFR4 — Fail-closed

Todo paso de la puerta que falle, lance o quede ambiguo → **deniega** (BR-9). Prohibido el
`try/except` que degrada a "permitir" (es el bug S2 del guard, que este mismo ciclo corrige).

---

## 6. Trazabilidad PBT (extensión bloqueante)

| Regla | Estado en U2 |
|---|---|
| **PBT-01** (identificar propiedades en Functional Design) | ✅ **6 propiedades** (U2-P1…U2-P6) en `functional-design/business-logic-model.md` §7 |
| **PBT-05** (oracle) | ✅ **Aplica** (a diferencia de U1, donde fue N/A): U2-P4 usa el **filesystem** como oráculo (el archivo no existe); U2-P5 usa el **JWT decodificado** |
| **PBT-09** (elección de herramienta con criterios) | ✅ **Hypothesis**, heredado de U1 (4 requisitos ya verificados). Sin herramienta nueva |
| Perfil de ejecución | `default` (100) en CI + **`thorough` (1000+)** para las 6, por ser **todas de seguridad** |
