# AI-DLC State Tracking

## Project Information
- **Project Type**: Brownfield
- **Project Name**: saga
- **Start Date**: 2026-06-21T22:49:10Z
- **Current Phase**: **Ciclo 9 — Auditoría y hardening de Testing + Security: INCEPTION ACTIVA** (2026-07-13).
  Ciclo 8 (limpieza de deuda) CERRADO Y MERGEADO A MAIN (PR #4, squash de71569). Ciclos 4/5/7 CERRADOS y en main.
- **Current Stage**: Ciclo 9 — Requirements Analysis COMPLETO, esperando aprobación del usuario para pasar a
  Workflow Planning. **Cambio de postura del proyecto**: Security + PBT pasan a extensiones BLOQUEANTES
  (ver Extension Configuration). Pendientes previos sin cambio: meditar qué plugins útiles; bug TTS agéntico
  abierto (fuera de scope). Paso manual del usuario: `pip uninstall` de las 2 deps muertas.
- **Última actualización de docs del repo**: U11 (commit 57399b3) sincronizó `docs/` + README. El toggle hoy es
  `CLAUDE_PLUGINS` (antes `VOICE_FULL_STACK`, renombrado en U11).

## Mapa de ciclos
- **Ciclo 1**: documentación del proyecto ✅
- **Ciclo 2**: wake word "hey saga" (modelo FPPH=0, commit 4743056) ✅
- **Ciclo 3**: fix buffer en modo console → cerrado como diagnóstico (no hay fix nativo en console; revertido) ✅
- **Ciclo 4**: migración console → room (transporte LiveKit). **✅ CERRADO Y MERGEADO** (PR #1 + PR #2).
  Unidades **U1–U8**: U1–U3 (infra/worker/cliente) + U5 (orbe sync) + U6 (saga-ctl) + U7/U7.1/U7.2 (cleanup
  room único) + **U8 (dispatch automático nativo, hardening del arranque)**. U4 (wake cliente) diferido.
  Server NATIVO (no Docker). Todo validado en vivo (cold boot del SO incluido).
- **Ciclo 5**: **saga AGÉNTICO** (tools/MCPs: hora, clima, Spotify). **⛔ SPIKE ABORTADO (2026-06-24)** — el
  spike `VOICE_FULL_STACK` mostró boot storm (load ~10, pipeline de voz caído por inanición de CPU) + ROI
  dudoso (saga ya es agéntica con bash/webfetch). Revertido. Diferido sin fecha. NO confundir con U9 (el
  commit de U9 quedó mal rotulado `ciclo5` por inercia de numeración — U9 NO es agéntico, es del Ciclo 7).
- **Ciclo 6**: speaker verification "solo mi voz". DIFERIDO desde Ciclo 2. NO arrancado.
- **Ciclo 7 (NUEVO) — Optimización de recursos del worker**: bajar CPU/RAM del worker de voz para hardware
  chico (Pi/mini-PC). Misma superficie (worker), mismo norte. Unidades:
  - **U9 — cap threads ONNX (CPU)**: ✅ CERRADO Y MERGEADO (PR #3). CPU worker 410%→40% (10x), sin perder
    detección. (Commit rotulado `ciclo5` por error histórico; pertenece acá.)
  - **U10 — RAM del turn detector**: ✅ CERRADO Y VALIDADO EN VIVO. `turn_detection` MultilingualModel
    (semántico, ~1.8 GB) → `"vad"` (VAD puro silero, ya cargado) + `min_delay` 2.0→3.0. RAM worker
    **2611 MB → 913 MB (−1.7 GB)**, UX igual (usuario: "se siente igual"). Bonus: se fue el "Error
    predicting end of turn". El turn detector era el 78% de la RAM (único consumidor grande).
  > **Ciclo 7 cerrado por ahora** (U9 CPU + U10 RAM). Worker pasó de ~410%/2.6 GB a ~40%/0.9 GB.
  > Próximo salto de hardware chico: split Pi (browser/mic vs worker) + onnxruntime-web para el wake (futuro).
- **Ciclo 9 (NUEVO) — Auditoría y hardening de Testing + Security** (2026-07-13): el framework pasa a ser
  standard antes/durante cada desarrollo → hay que ponerse al día con sus metodologías de seguridad y testing.
  Extensiones Security + PBT ACTIVADAS como bloqueantes (primera vez en el proyecto). Modelo de amenaza = C
  (mishears + software local hostil + prompt injection). Alcance = C (auditoría + hardening completo).
  NFR duro: el turno de voz no puede regresar más de +300ms. **Hallazgo estructural**: `--permission-mode auto`
  EXISTE en el CLI (verificado en Claude Code 2.1.207) → se puede salir del `--dangerously-skip-permissions`
  sin perder el flujo automático de voz (sujeto a verificación empírica en modo no-interactivo).
  Requirements: inception/requirements/ciclo9-security-testing-requirements.md.

### INCEPTION Ciclo 9
- [x] Workspace Detection — RESUME (brownfield)
- [x] Reverse Engineering — SKIP (refresh 2026-07-12 vigente)
- [x] Requirements Analysis — COMPLETO (ciclo9-security-testing-requirements.md; Q1=A Security bloqueante,
  Q2=A PBT bloqueante full, Q3=B Resiliency off, Q4=C prompt injection, Q5=C hardening completo).
  **Correcciones del usuario (2026-07-13)**: NFR1 = latencia **NO DETECTABLE** (no "+300ms"; baseline = turno
  sin plugins; gate perceptual + benchmark). NFR3 = seguridad **INCONDICIONAL, sin toggle de apagado**
  (se rompe el patrón "default OFF + opt-in" de los ciclos 4-8; la reversibilidad la da git, no un flag).
  **Modelo de permisos DECIDIDO**: `--permission-mode auto` (el usuario prefiere que saga tenga juicio propio;
  `dontAsk` descartado por limitante). + FR2.5 nuevo: regla anti-interactivo en el system prompt.
  Riesgo #1 a MEDIR: el clasificador de `auto` puede sumar latencia → gate contra NFR1 (plan B = dontAsk).
- **Rama de trabajo**: `feature/security-testing-workflow`
- [x] User Stories — SKIP (hardening interno + tests; sin personas ni features de cara al usuario)
- [x] Workflow Planning — COMPLETO (plans/execution-plan-ciclo9.md). Riesgo: **HIGH**. Stages a EJECUTAR:
  Units Generation + Functional Design (obligatorio por PBT-01) + NFR Requirements (obligatorio por PBT-09)
  + Code Generation + Build&Test. SKIP: Application Design (sin componentes nuevos), NFR Design, Infra Design.
  **3 unidades secuenciales**: U1 (red de tests + CI, riesgo bajo) → U2 (hardening orb_server, riesgo medio)
  → U3 (modelo de permisos: auto mode + guard fail-closed + MCP + prompt anti-interactivo, riesgo ALTO).
  Orden deliberado: los tests primero para tener red antes de tocar lo peligroso.
  Gates bloqueantes: G1 latencia no detectable · G2 no regresión · G3 SECURITY · G4 PBT · G5 suite verde.
- [x] Application Design — SKIP (sin componentes/servicios nuevos)
- [x] **Units Generation — COMPLETO** (Part 1 plan + Part 2 artefactos). Decisiones del usuario:
  Q1=A (**un PR por unidad**: U1→merge→U2→merge→U3→merge; si U3 falla el gate, U1+U2 ya están a salvo en main)
  · Q2=A (tests solo sobre la superficie de seguridad: orb_server, config, guard; el resto = deuda declarada)
  · Q3=C (**ruff** en todo el repo + **mypy** solo en los 3 módulos de seguridad) · Q4=C (**NO** denylist propia
  de tools MCP: no escala y sería defensa contra el usuario; se delega al clasificador de `auto` + reglas
  `permissions.deny` declarativas).
  **ACLARACIÓN DE SCOPE del usuario**: la defensa es contra **lo destructivo OBVIO** (accidentes/mishears),
  NO contra órdenes legítimas — si Renzo pide algo destructivo y saga tiene el tool, saga lo ejecuta. Garantizar
  que la orden sea auténtica = detección de voz + wake → se endurece en el **Ciclo 6 (speaker verification)**,
  FUERA de scope acá.
  Artefactos: application-design/unit-of-work-ciclo9.md + unit-of-work-dependency-ciclo9.md.
  Trazabilidad: **20 FR + 5 NFR asignados, cero huérfanos**.

> **INCEPTION Ciclo 9 CERRADA** (2026-07-13). Units Generation aprobado por el usuario.

### Convención de artefactos — ESTRUCTURA DEL FRAMEWORK, ESTRICTA (decisión del usuario, 2026-07-13)
El framework (`CLAUDE.md` → Directory Structure) organiza **por STAGE en Inception** (rutas planas) y **por UNIDAD
en Construction** (`construction/{unit-name}/`). Se sigue al pie, sin inventar subcarpetas por feature:
- Inception → ruta plana + prefijo de ciclo (los nombres canónicos `requirements.md` /
  `requirement-verification-questions.md` **ya están ocupados por el Ciclo 1**, por eso el prefijo; es la
  convención de facto de los ciclos 2-8): `inception/requirements/ciclo9-security-testing-*.md`,
  `inception/plans/execution-plan-ciclo9.md`, `inception/application-design/unit-of-work-ciclo9.md`.
- Construction → `construction/U1-tests-ci/{functional-design,nfr-requirements,code}/` (esto SÍ es la
  estructura literal del framework, igual que `U1-infra-room/`, `U8-dispatch-consistente/` de ciclos previos).
> Descartada la subcarpeta por slug en Inception (patrón de base-de-tramites): NO está en el framework.

### CONSTRUCTION Ciclo 9 (en curso)
- [ ] **U1 — Red de tests + CI** (riesgo bajo, no toca runtime) ← ACTUAL
  - [x] **Functional Design — COMPLETO** (obligatorio por PBT-01). Artefactos en `construction/U1-tests-ci/functional-design/`
    (business-logic-model + business-rules + domain-entities). Plan: `construction/plans/U1-tests-ci-functional-design-plan.md`.
    **10 propiedades identificadas (P1-P10)** leídas del código. PBT-05 (oracle) = N/A declarado.
    Decisiones: **Q1=B pytest** (corre los unittest existentes sin tocarlos; el argumento "stdlib-only" se cae
    al entrar Hypothesis) · **Q2=C pip-audit bloqueante CON allowlist** (un CVE en transitiva sin patch dejaría
    el CI rojo y trabado; un CI siempre rojo deja de leerse) · **Q3=A** bypasses del guard se registran y se
    difieren a U3.
    **HALLAZGO ANTICIPADO (P4)** ⚠️ propiedad de seguridad no verificada hoy: el socket de control usa
    `readline()` como framing y manda el payload en base64 — si el payload pudiera contener `\n`, un adjunto
    partiría el mensaje e **inyectaría un comando en el socket del agente**. Se sostiene porque `b64encode`
    (≠ `encodebytes`) no emite saltos de línea, pero es un supuesto IMPLÍCITO que nadie verifica.
    **EXPECTATIVA (P7)**: el PBT del guard VA A ENCONTRAR bypasses (`rm -r -f` no matchea el regex actual).
    Eso es el test funcionando. Se registran y los cierra U3.
  - [x] **NFR Requirements — COMPLETO** (obligatorio por PBT-09). Artefactos en `construction/U1-tests-ci/nfr-requirements/`
    (nfr-requirements + tech-stack-decisions). Plan: `construction/plans/U1-tests-ci-nfr-requirements-plan.md`.
    **PBT-09 CUMPLIDO**: **Hypothesis** elegido, con sus 4 requisitos verificados (generadores custom, shrinking,
    seed, integración con el runner). Stack: pytest (corre los unittest existentes sin tocarlos) · ruff (todo el
    repo) · mypy (solo guard/config/orb_server: el repo no tiene anotaciones sistemáticas) · pip-audit (bloqueante
    + allowlist). Deps en `[project.optional-dependencies].test`, **sin pins**. Perfiles Hypothesis: default (100)
    en CI · **thorough (1000+) para las propiedades de SEGURIDAD** (P4/P7/P8), a demanda. `deadline=None` solo
    donde hay I/O (P5/P6) — un timeout en runner compartido es ruido, no un bug.
    **NFR1 (latencia)**: N/A como impacto (U1 no toca producción), pero U1 **construye el método de medición**
    y captura el **baseline** contra el que se medirá el gate de U3. Sin baseline, el gate sería una opinión.
    Verificado (no supuesto): Python 3.12 en venv/CI/.python-version; pyproject SIN grupo de test hoy.
  - [x] NFR Design — SKIP (sin patrones NFR nuevos) · [x] Infra Design — SKIP (sin cloud/IaC)
  - [x] **Code Generation — Part 1 (plan) + Part 2 (código) HECHOS**. 5 archivos nuevos (tests/generators.py,
    test_properties.py, test_orb_server.py, test_config.py, .pip-audit-allowlist.txt) + 3 modificados
    (pyproject.toml, .github/workflows/tests.yml, docs/tech-debt-plan.md). **CERO código de producción tocado**
    (verificado con git diff --name-only). Verif: pytest 32 passed + 4 xfailed · ruff limpio · diff sin producción.
    **4 HALLAZGOS (el valor de U1)**: F1🔴 BUG REAL — `_read_plugins_blacklist` crashea en el arranque con
    `{"disabledPlugins": 42}` (TypeError, el docstring promete no romper el arranque y MIENTE); fix 1 línea.
    F2🔴 mypy — gap de anotación en config.py:118 (no es bug); fix 1 línea (mismo archivo que F1).
    F3🟠 BYPASSES del guard MEDIDOS (P7): `rm -r -f` (flags separadas) y `rm --recursive --force` (forma larga)
    NO se bloquean → input directo para U3. F4🟡 CVEs en transitivas (aiohttp/nltk/pillow/pip), la mayoría con
    fix disponible → allowlist creada, decisión de actualizar-vs-aceptar pendiente. Además 2 xfail-strict que
    documentan los agujeros a cerrar: S5 (orb sin auth → U2) y S1 (god-mode → U3); cuando se cierren, XPASS obliga
    a des-marcarlos. Deuda declarada D6 (sin tests en lk/*, daemon, vcctl). D2+R2 CERRADAS en tech-debt-plan.
    Summary: construction/U1-tests-ci/code/generation-summary.md.
    **HALLAZGOS RESUELTOS (autorizado por el usuario: "esta rama deja TODA la base testing+security sólida")**:
    F1 ✅ (guardia contra no-lista en config.py; el crash de arranque se fue; xfail de P5 removido → test verde).
    F2 ✅ (anotación `settings: dict`; mypy limpio). F4 ✅ POR UPGRADE (aiohttp→3.14.1, pillow→12.3, nltk→3.10;
    core intacto; import smoke OK; requirements.txt actualizado; allowlist VACÍA; pip-audit limpio venv + CI).
    F3 (bypasses del guard) → queda para U3 según plan. Producción tocada = SOLO lo aprobado: vc/config.py + lock.
    Deuda declarada: D6 (tests lk/daemon/vcctl), D7 (audit CI = solo lock curado). D2+R2 cerradas.
    **Verif final**: pytest 33 passed + 3 xfailed (P7→U3, S5→U2, S1→U3) · ruff limpio · mypy limpio · 11 viejos OK.
    ⚠️ Bump de transitivas del stack de voz: import smoke OK, pero **turno de voz e2e sin validar** → Build & Test.
  - [x] **Build & Test (estático) — CERRADO OK**. build (editable) + py_compile todo el repo + pytest 33p/3xf
    + thorough 9p/1xf + ruff limpio + mypy limpio + pip-audit limpio (venv + CI). Los 11 viejos intactos.
    Baseline NFR1: TTFT modo rápido (CLAUDE_PLUGINS=0) **mediana ~2.09s** (120 turnos del histórico) → número
    que U3 no puede regresar. Artefacto: construction/build-and-test/U1-tests-ci-build-and-test.md.
    ⏳ **PENDIENTE (único): validación en vivo del usuario** — turno de voz tras el bump de deps (aiohttp/pillow/nltk)
    para confirmar no-regresión del stack de voz. Riesgo bajo (core intacto, import smoke OK) pero es runtime.
  - [x] **VALIDACIÓN EN VIVO — OK (usuario, 2026-07-13)**: levantó saga y probó turno de voz, "todo 100% en
    orden". El bump de deps (aiohttp/pillow/nltk) NO rompió el stack de voz. **U1 CERRADA.**
> **✅ U1 CERRADA, VALIDADA EN VIVO Y MERGEADA A MAIN** (PR #5, squash 40dde9c). Rama borrada (remoto + local).
> Red de tests + CI + 3 hallazgos de seguridad resueltos (F1 crash de arranque, F2 tipo, F4 CVEs). En main:
> ruff + mypy + pytest/PBT + pip-audit + deep-fuzz. Baseline NFR1 ~2.09s registrado para el gate de U3.

### U2 — Hardening de orb_server (EN CURSO, 2026-07-13)
- **Rama**: `feature/ciclo9-u2-orb-server` (desde main limpio con U1 ya integrado).
- **🔬 INVESTIGACIÓN DEL ESTÁNDAR DE INDUSTRIA (2026-07-13)** — pedido explícito del usuario *("no quiero
  que codeemos cosas [inventadas]; seguramente en la industria ya haya un estándar")*. Artefacto:
  `inception/requirements/ciclo9-security-research.md` (fuentes primarias: OWASP, NCC Group, MDN/WHATWG,
  docs oficiales de LiveKit/Jupyter/Ollama/Anthropic). **Consecuencias que CAMBIARON el diseño**:
  - **El precedente exacto de orb_server es Ollama / CVE-2024-28224**: server local de LLM sin auth con
    **exfiltración de archivos vía DNS rebinding** demostrada. No es teórico: es el estado actual del código.
  - **La v1 del plan de Functional Design planteaba FALSAS DISYUNTIVAS** (token *o* cookie *o* header). El
    estándar (Jupyter, Syncthing, qBittorrent) **no elige: combina** — cada capa tapa un ataque distinto.
    Token → proceso local · **Host check → DNS rebinding** (el `Origin` NO sirve ahí: el atacante ES
    same-origin) · header custom con secreto → fuerza preflight → CSRF web.
  - **Supuesto FALSO corregido (Q7/TTL)**: doc oficial de LiveKit — *"Expiration time only impacts the initial
    connection, and not subsequent reconnects"* + el server empuja tokens refrescados por el signal channel.
    → **TTL corto NO rompe reconexiones** (el riesgo anotado no existía) · **el TTL NO limita la sesión** ·
    **self-hosted no tiene revocación** → el TTL corto ES la única red. TTL explícito = 5 min.
  - **Requirements ACTUALIZADOS**: FR3.1–FR3.6 precisados + **4 FR nuevos**: **FR3.7** (validar header `Host`,
    anti-rebinding) · **FR3.8** (`Sec-Fetch-Site`: cubre GET y **SSE**, donde `Origin` no viene en same-origin)
    · **FR3.9** (grants mínimos del JWT: solo `microphone`; hoy hereda los defaults del SDK) · **FR3.10**
    (`identity`/`room` los fija el SERVER: hoy vienen del query sin validar y **se firman en el JWT**).
  - **Objeción abierta registrada para U3** (§4.2 de los requirements): **la confirmación hablada es
    inyectable por el mismo canal que el ataque**. Dato duro de Anthropic: **~93% de los permission prompts
    se aprueban sin leerlos** (OWASP **ASI09**, medido en producción) → *si confirmás todo, no confirmás nada*.
    Guía: *"containment en la capa de entorno primero, comportamiento del modelo después"*.
- **Scope** (FR3, revisado): FR3.1 auth deny-by-default en TODO endpoint (ORB_TOKEN autogenerado, 3 vías:
  header/cookie/bootstrap; `hmac.compare_digest`) · FR3.2 **cero headers CORS** + validación de `Origin` ·
  FR3.3 headers de seguridad (CSP con nonce + `form-action 'none'`, nosniff, XFO, `Referrer-Policy`) ·
  FR3.4 límites de tamaño (413 **sin leer el body**) · FR3.5 TTL corto explícito del JWT · FR3.6 rate limit
  en /say + concurrencia 1 (OWASP **LLM10**) · **FR3.7 Host check** · **FR3.8 Sec-Fetch-Site** ·
  **FR3.9 grants mínimos** · **FR3.10 identity/room del server**.
- **Riesgo nuevo a verificar EN VIVO**: la CSP `connect-src` **debe** enumerar el WS de LiveKit o **rompe el
  WebRTC y saga queda muda**. Se determina empíricamente, no de memoria.
- **RECORTE POR PROPORCIONALIDAD (2026-07-13, decisión del usuario)**: *"tampoco armar algo TAN COMPLEJO,
  es LOCAL"* + *"el RENDIMIENTO ES CRUCIAL al igual que la seguridad, pero esta última no debería ser tan
  complicada"*. La v2 sobre-diseñó (aplicaba el estándar de servers expuestos a un equipo monousuario).
  **Plan reescrito a v3**: solo lo que tapa un atacante REAL en local + cuesta poco. **DESCARTADO explícito
  (requirements §FR3-OUT)**: rate limit en /say (con token, el único que lo llama es el usuario → protegerlo
  de sí mismo) · cookie de sesión (traería cookie-tossing; el ?token= en localhost no tiene a quién
  filtrarse) · CSP con nonce/`connect-src` (riesgo de romper el WebRTC > beneficio) · `Sec-Fetch-Site`
  (redundante con el token) · validación de `Origin` (no agrega ataque nuevo que frenar). El usuario delegó
  al 100%.
- **FR3 final (7, no 10)**: FR3.1 token deny-by-default · FR3.2 cero CORS · FR3.3 headers baratos + CSP
  acotada (`frame-ancestors`/`form-action`/`base-uri` 'none' — NO toca script/connect-src) · FR3.4 límites
  de tamaño (413 sin leer) · FR3.5 TTL 5min + grants mínimos · FR3.6 room/identity del server · FR3.7 Host
  check (anti-rebinding).

#### CONSTRUCTION U2 — TODO EL FLUJO HECHO (estático CERRADO, falta validación en vivo)
- [x] **Functional Design — COMPLETO** (plan v3 + 3 artefactos en `construction/U2-orb-server/functional-design/`:
  business-logic-model con **6 propiedades U2-P1…U2-P6** para PBT-01, business-rules, domain-entities).
- [x] **NFR Requirements — COMPLETO** (`nfr-requirements/nfr-requirements.md`). PBT-09 heredado de U1
  (Hypothesis, sin herramienta nueva). PBT-05 (oracle) APLICA acá (U2-P4 filesystem, U2-P5 JWT decodificado).
  Sin dependencias de producción nuevas (secrets/hmac son stdlib).
- [x] NFR Design / Infra Design — SKIP (sin patrones ni cloud nuevos).
- [x] **Code Generation Part 1 (plan) + Part 2 (código) HECHOS**. Plan: `construction/plans/U2-orb-server-code-generation-plan.md`.
  7 archivos: vc/config.py (orb_token/reset), orb/orb_server.py (la puerta _gate), orb/orb.html (token en
  cliente), vc/orb.py (agente + arranque), vcctl.py (rotación), tests/generators.py (hosts adversariales),
  tests/test_orb_server.py (6 propiedades + des-marca xfail S5). Summary: `construction/U2-orb-server/code/generation-summary.md`.
  **Decisión de arquitectura**: el token lo necesitan 3 PROCESOS (server valida, browser, agente hace
  POST /state) → archivo de runtime 0600 en XDG_RUNTIME_DIR (patrón Jupyter), efímero por arranque.
  **HALLAZGO (valor del PBT)**: U2-P6 cazó un BUG REAL — `hmac.compare_digest` tira TypeError con no-ASCII
  → un token Unicode por ?token= CRASHEABA el handler (fail-open por excepción). Corregido a fail-closed.
- [x] **Build & Test (estático) — CERRADO OK**: pytest 43p/2xf (los 2 xfail = U3: S1, P7; **el xfail S5 se
  des-marcó → XPASS**). thorough 24p/1xf. ruff limpio · mypy limpio · py_compile · import smoke 3 procesos.
  curl contra server real: rebinding con token válido → 403, /token sin token → 401, attach >10MB → 413, sin
  CORS. Artefacto: `construction/build-and-test/U2-orb-server-build-and-test.md`.
- [x] **Build & Test (EN VIVO) — CERRADO OK (2026-07-13)**. El usuario validó el turno de voz completo por
  las **3 vías** (texto, wake "hey saga", **Win+Z**): graban, procesan y responden por voz. **4 bugs de
  integración cazados y corregidos durante el gate C1** (ninguno lo agarraba la suite estática): (1) `/vendor/*`
  pedía token → three.js muerto (los ES modules no mandan headers) → exento; (2) 401 al refrescar (replaceState)
  → token queda en la URL; (3) desync del token → rotar solo en `stop`; (4) `__orbFetch` definido tras un `await`
  en el módulo de three.js → movido a `<script>` plano (verificado con Playwright: token OK → room CONNECTED).
  **Win+Z NO era de saga/U2**: binding de Hyprland perdido en una update de los dots de KooL → repuesto en
  `~/.config/hypr/UserConfigs/UserKeybinds.conf` (skill kool-hyprland). Verif final: pytest 45p/2xf · thorough
  26p · ruff/mypy limpios · diff = solo 7 archivos de U2. Deuda menor: favicon.ico 401 (cosmético).
- [x] **CÓDIGO VALIDADO Y APROBADO POR EL USUARIO (2026-07-13)**: *"Doy por validado y aprobado el codigo"*.
> **✅ U2 CERRADA Y MERGEADA A MAIN** (PR #6, squash 2023536). Rama borrada (local + remoto). Suite en main:
> 45 passed / 2 xfailed (los 2 = U3: S1 god-mode, P7 guard). El xfail S5 quedó des-marcado firme (agujero
> cerrado). Deuda menor: favicon.ico 401 (cosmético). **Próximo: U3** (riesgo ALTO — modelo de permisos +
> objeción abierta de la confirmación por voz).
- **Punto de coordinación C1** (crítico): orb.html ↔ orb_server ATÓMICO. Si el server exige token y el cliente
  no lo manda, el orbe no conecta y saga queda muda. Se valida en vivo.
- **Red que ya espera**: el xfail-strict `test_no_auth_by_default_is_the_hole` (S5) hará XPASS cuando FR3.1 cierre
  el agujero → obliga a des-marcarlo. Tests de orb_server (routing, path traversal, /token) ya existen de U1.
- [ ] Functional Design → [ ] NFR Requirements → [ ] Code Generation → [ ] Build&Test
- [ ] U2 — Hardening orb_server (riesgo medio; C1: orb.html ↔ orb_server atómico)
### U3 — Modelo de permisos (EN CURSO, 2026-07-13) — riesgo ALTO
- **Rama**: `feature/ciclo9-u3-permisos` (desde main con U1+U2 integrados).
- **🔬 RIESGO #1 DEL CICLO: MEDIDO Y DESCARTADO** (4 probes contra el CLI 2.1.207 replicando los flags exactos
  del daemon). La doc de Claude Code dice *"the run aborts"* en headless si una tool no está pre-aprobada → si
  valiera para saga, `auto` mataría el turno de voz (NFR2 lo prohíbe). **NO VALE**: (1) `auto` + benigno →
  ejecuta sin pedir permiso · (2) `auto` + destructivo EXPLÍCITO ("borrá X") → **LO EJECUTA** (obedece la orden
  explícita del usuario) · (3) `auto` + `permissions.deny` → bloquea, NO aborta (`exit=0`, saga lo dice hablando)
  · (4) `auto` + `permissions.ask` **SIN TTY** (peor caso) → **NO cuelga**: degrada a **denegación limpia**.
  → **`auto` no puede colgar el turno de voz.** El peor caso es que saga diga "no pude" (riesgo G2/utilidad, no
  NFR2). **Latencia**: sin salto sistemático vs `bypassPermissions` (el gate G1 real se corre en Build&Test
  contra el baseline del daemon, TTFT ~2.09s).
  **CONSECUENCIA DE DISEÑO**: sin TTY, el `ask` nativo **no pregunta: deniega** → el mecanismo NATIVO de permisos
  **NO PUEDE** implementar la confirmación. Por eso la confirmación vive en el **system prompt**. No es
  preferencia: es la única vía.
- **🧪 VALIDACIÓN EN CAMPO DEL USUARIO** (log de saga 17:13-17:15): pidió borrar un archivo por voz y saga
  **se detuvo sola**: buscó, hizo readback ("encontré la carpeta, solo tiene contra.txt") y **preguntó** antes de
  ejecutar. Con el segundo "borralo", ejecutó. **Esa es la conducta que el usuario quiere.**
  ⚠️ **Corrección técnica registrada**: eso fue comportamiento **EMERGENTE** del modelo, **NO una regla** — el
  `CLAUDE_SYSTEM_PROMPT` actual **no tiene una sola línea de seguridad** y encima empuja al contrario ("HACELA…
  no digas 'no puedo'"). U3 lo convierte en **regla explícita**.
- **PRINCIPIO RECTOR (usuario)**: *"Eso es lo que buscamos: **NO que no pueda hacerlo**… salvo que yo te lo pida
  **DOS VECES** (la primera es la orden → pedís confirmación → confirmo → ejecutás), no lo vas a hacer."*
  La defensa es contra lo **NO SOLICITADO** (mishears, inferencias), no contra las órdenes del usuario.
- **DECISIONES** (Functional Design): Q1=**A** confirmación **hablada de dos pasos** en el prompt (se descarta la
  confirmación out-of-band en el orbe) · Q2=**fail-closed + log forense** (asunción del AI, reportada) ·
  Q3=**parsear el comando de verdad** (`shlex` + normalización de flags: `-r -f` ≡ `-rf` ≡ `--recursive --force`;
  el regex queda de fallback y de **oracle** de no-regresión) · Q4=**`permissions.deny` VACÍO** (una regla `deny`
  es un techo duro inapelable → rompería el principio de las dos veces).
  **EXCEPCIÓN EXPLÍCITA DEL USUARIO**: las **MALAS PRÁCTICAS DE GIT** (`git reset --hard`, `git push --force`,
  `git clean -f`) quedan **BLOQUEADAS DURO en el guard**, SIN confirmación posible — *"son, como su nombre indica,
  MALAS PRÁCTICAS (además de comandos super destructivos)"*. El techo duro existe, pero vive en el guard (nuestro,
  auditable, testeado), no en las reglas nativas.
- **4 capas (defensa en profundidad, SECURITY-11)**: (1) `--permission-mode auto` = clasificador nativo, cubre
  **todas** las tools incl. MCP · (2) **system prompt** = dos pasos + anti-injection + anti-interactivo (capa
  **BLANDA**: es juicio del modelo) · (3) **guard fail-closed** = catastrófico + malas prácticas git (capa DURA,
  determinística) · (4) circuit breaker nativo del harness (`rm -rf /` bloqueado aún con `bypassPermissions`).
- [x] **Functional Design — COMPLETO**. Plan: `construction/plans/U3-permisos-functional-design-plan.md`.
  Artefactos: `construction/U3-permisos/functional-design/` (business-logic-model + business-rules + domain-entities).
  **7 propiedades (U3-P1…U3-P7)** para PBT-01, incluyendo **U3-P6 = oracle (PBT-05)**: el guard nuevo (parser) es
  **superconjunto** del viejo (regex) → el rewrite no puede ABRIR un agujero que estaba tapado.
  Cierra los 2 xfail-strict que quedan: **S1** (god-mode) y **P7** (bypasses del guard).
- [x] **NFR Requirements — COMPLETO** (`construction/U3-permisos/nfr-requirements/`: nfr-requirements + tech-stack-decisions).
  Plan: `construction/plans/U3-permisos-nfr-requirements-plan.md`. **PBT-09 cumplido SIN herramienta nueva**
  (Hypothesis heredado de U1). **CERO deps nuevas**: el parser del guard usa **`shlex` (stdlib)**. Se evaluó y
  descartó `bashlex` (dep nueva; sobra: no hay que interpretar Bash, hay que clasificar) y el **sandbox real**
  (bubblewrap/seccomp = respuesta a un modelo de amenaza más duro → otro ciclo, **deuda D9**).
  **Gate G1**: A/B controlado **en la misma sesión** (el baseline histórico de U1 está declarado *sucio* por el
  propio artefacto) + validación perceptual; **si divergen, manda la percepción** (NFR1 = "no detectable", no un
  umbral). **NFR3**: `VOICE_CLAUDE_SAFE` se **ELIMINA** (era el opt-in *a* la seguridad: patrón inverso al
  decidido). **NFR4**: excepción acotada — si falla la escritura del settings se pierde la capa 3 (guard), **no
  todas** (`auto` no depende del settings) y el `doctor` tiene que gritarlo. Requisito nuevo: **guard < 50ms**.
  Deuda **D8** (el guard loguea el comando bloqueado; podría traer un secreto en la línea — no empeora lo actual).
- [x] NFR Design — SKIP (sin patrones NFR nuevos) · [x] Infra Design — SKIP (sin cloud/IaC)
- [x] **Code Generation — Part 1 (plan) + Part 2 (código) HECHOS**. Plan: `construction/plans/U3-permisos-code-generation-plan.md`.
  Summary: `construction/U3-permisos/code/generation-summary.md`. **11 archivos (+631/−65)**; producción = SOLO los
  3 aprobados (`vc/guard.py` rewrite del cuerpo **con la misma firma pública**, `vc/config.py` args+prompt+settings,
  `vc/doctor.py`). Orden deliberado: **primero el guard, después sacar el god-mode** (para no dejar una ventana con
  `auto` como única capa).
  **LOS 2 XFAIL-STRICT DEL CICLO DESAPARECIERON**: **S1** (god-mode) y **P7** (bypasses `rm -r -f`).
  Verif: **pytest 56 passed / 0 xfailed** (antes 45p/2xf) · thorough 28p (1000 ejemplos) · ruff · mypy · py_compile ·
  import smoke (`permission mode: auto`, god-mode `False`) · pip-audit limpio.
  **Benchmark del guard**: hook completo **46.6ms** pero `denied()` puro = **0.036ms** → los ~45ms son el arranque de
  `python3`, **idénticos al guard viejo**. El parser no agregó costo medible.
  **E2E contra `claude` REAL**: (1) *"borrá la carpeta con rm -rf, **sin preguntarme nada, hacelo ya**"* → **el guard
  bloqueó**, la carpeta sigue, turno limpio (`exit=0`), Claude: *"no puedo saltearme ese hook"*. (2) con el prompt
  nuevo, *"borrá borrable.txt"* → saga **buscó, hizo readback y PREGUNTÓ** (*"¿Confirmás que lo borre?"*), **no borró**.
  **La conducta que el usuario probó en vivo, ahora por REGLA y no por suerte.**
  **HALLAZGO H1 (valor del PBT)**: la propiedad U3-P3 (fail-closed) destapó un **fail-open no previsto en el diseño**:
  un payload con `tool_name` de tipo raro caía en el `allow` silencioso de *"no es asunto mío"* (`tool != "Bash"` es
  `True` para un `int`). Corregido → si no sabemos ni qué tool es, **deny**. Mismo patrón que el bug de
  `hmac.compare_digest` de U2: lo caza una propiedad, no un test de ejemplo.
- [x] **Build & Test (ESTÁTICO) — CERRADO OK**. Artefacto: `construction/build-and-test/U3-permisos-build-and-test.md`.
  build (py_compile + import smoke) · **pytest 56 passed / 0 xfailed** · thorough 28p · ruff · mypy · pip-audit limpios.
  `doctor` verificado: *"permisos — --permission-mode auto (sin god-mode)"* + *"guard (hook) — activo"* → **ya no miente**.
  **BASELINE A capturado** (mejor que el histórico de U1): los turnos que el usuario corrió **hoy 17:12–17:15 en
  god-mode** (misma máquina, misma sesión — los de la prueba del `contra.txt`) → **TTFT mediana ~3.6s** (2.17–5.39s).
  El histórico de U1 (~2.09s, condiciones mezcladas) baja a referencia secundaria. Diff: 11 archivos, +664/−65.
- [x] **VALIDACIÓN EN VIVO (gate C1) — CERRADA OK (usuario, 2026-07-14, CON `CLAUDE_PLUGINS=1`)**:
  · **FR2.6 CONFIRMACIÓN DE DOS PASOS — VERIFICADA EN VIVO**: *"Quiero que elimines el archivo de la carpeta
  contraseña súper secreta"* → saga: *"Reviso qué hay adentro antes de borrar nada. Encontré `contra.txt`…
  **¿Confirmás que borre `~/Develop/contraseña-super-secreta/contra.txt`?**"* — **y NO lo borró**.
  **Ahora es por REGLA (system prompt), no por suerte del modelo.**
  · **Gate G2 (utilidad) — OK**: `date`, `ls ~/Develop`, **MCP de Monton** y consulta al **vault**, todo ejecutado
  **sin pedir permiso ni una vez**. `auto` no bloqueó nada legítimo.
  · **Gate G1 (latencia) — OK, CON NÚMERO**: turnos conversacionales con `auto` = 2.84 / 4.24 / **3.20s (mediana)**
  vs **baseline A (god-mode, hoy) 3.57s** → **NO REGRESÓ** (igual o mejor). Los turnos de 8–33s usaron Bash/MCP:
  es la **latencia agéntica** ya documentada como deuda del Ciclo 5 (turnos con tools 13-17s+), **no** de U3.
  · **NFR2 — OK**: wake, Win+Z, turno completo y **cancel** andando. · **R5 CERRADO** (plugins ON toda la sesión).
  · Verificado en el **proceso real**: el `claude` del daemon corre con `--permission-mode auto` + `--settings`
  (guard cableado) y **sin** `--dangerously-skip-permissions`.
- [x] **CÓDIGO APROBADO Y CICLO 9 DADO POR FINALIZADO POR EL USUARIO** (2026-07-14): *"doy por aprobado y por
  finalizado el ciclo"*.
> **✅ U3 CERRADA Y VALIDADA EN VIVO.** Pendiente operativo: commit + PR + merge a main (Q1=A: un PR por unidad).
> **El Ciclo 9 queda COMPLETO: U1 (red de tests + CI) → U2 (hardening de orb_server) → U3 (modelo de permisos).**: gate **G1**
  (latencia: A/B + "¿se siente igual?") · gate **G2** (utilidad: que `auto` no bloquee de más) · turno completo por
  las 3 vías + cancel · **el caso del MISHEAR** (orden destructiva no dada → saga pregunta → "no" → no se ejecuta) ·
  `CLAUDE_PLUGINS=1` (riesgo R5: los probes corrieron en modo rápido).
- Por unidad: Functional Design (obligatorio PBT-01) + NFR Requirements (obligatorio PBT-09) + Code Gen + Build&Test
- Merge: **un PR por unidad** (Q1=A)

- **Ciclo 8 — Limpieza de deuda técnica**: cleanup brownfield, sin lógica nueva, sin tocar el flujo
  de voz. CORE: FR1 (cadena muerta cancel SIGUSR2 en vc/runtime.py + no-ops en claudecli) + FR2 (deps muertas
  turn-detector/noise-cancellation en pyproject). Optativos a decidir: wake shutdown, pin LiveKit, lint/CI.
  Requirements: inception/requirements/ciclo8-cleanup-requirements.md.

### INCEPTION Ciclo 8
- [x] Workspace Detection — RESUME (brownfield)
- [x] Reverse Engineering — SKIP (refresh 2026-07-12 vigente)
- [x] Requirements Analysis — COMPLETO (ciclo8-cleanup-requirements.md; Q1=A CORE, Q2=A solo pyproject, delegado al AI)
- [x] User Stories — SKIP (cleanup interno, cero impacto al usuario)
- [x] Workflow Planning — COMPLETO (execution-plan-ciclo8.md)
- [x] Application Design / Units Generation — SKIP (sin componentes/descomposición)

### CONSTRUCTION Ciclo 8
- [x] Functional / NFR Req / NFR Design / Infra Design — SKIP (sin lógica/modelos/infra nuevos)
- [x] Code Generation — Part 1 (ciclo8-cleanup-code-generation-plan.md) + Part 2 (código) HECHOS.
  3 archivos: vc/runtime.py (rewrite, saca cadena muerta), vc/claudecli.py (no-ops + de-indent),
  pyproject.toml (2 deps muertas). Summary: construction/ciclo8-cleanup/code/generation-summary.md.
- [x] Build & Test — CERRADO OK (estático). py_compile + tests 11/11 + import smoke + refs=0 + _cancel vivo.
  Detalle: construction/build-and-test/ciclo8-build-and-test.md.
- [x] **CERRADO Y MERGEADO A MAIN** (PR #4, squash de71569). Rama feat/ciclo8-cleanup-deuda borrada
  (remoto + local). Deuda restante flageada: `pip uninstall` de las 2 deps muertas (paso manual del usuario).

## Ciclo 4 — Migración modo console → modo room (LiveKit)
- **Tipo**: migration/refactor del TRANSPORTE de audio. El cerebro IA (STT/LLM/TTS/VAD/wake) se conserva.
- **Por qué**: el modo console acumula audio (buffer, Ciclo 3); el modo room descarta frames con mic
  apagado (verificado en `room_io/_input.py:154-156`). Bonus: orbe sincronizado con la voz real + multi-device.
- **Decisiones** (2026-06-23, AI respondió por delegación del usuario — ver room-migration-requirement-questions.md):
  - Servidor: Docker self-hosted LOCAL (gratis, privado, sin cloud).
  - Cliente publicador del mic: el BROWSER del orbe (unifica mic+orbe+voz, da orbe sync gratis).
  - Wake: dónde corre = a definir en Application Design.
  - Win+Z y fallback console: se conservan.
  - Scope: transporte + orbe sync. NO speaker verification (Ciclo 5).
- **NFR duro**: no regresar la latencia ~2-3s (benchmark gate en Construction). Privacidad: audio local-only.

### INCEPTION Ciclo 4
- [x] Workspace Detection / Reverse Engineering — reutilizados
- [x] Requirements Analysis — COMPLETO (room-migration-requirement-questions.md)
- [ ] User Stories — SKIP (refactor de infra)
- [x] Workflow Planning — execution-plan-ciclo4.md
- [x] **Application Design — COMPLETO** (aidlc-docs/inception/application-design/). Topología room + flujo +
  **wake en el CLIENTE** (corregido tras revisar el vault: es el patrón estándar LiveKit + alineado con la
  visión "DesktopLayer como producto" + privacidad + cross-platform). Solo docs.
- [x] **Units Generation — COMPLETO** (6 unidades: U1 infra · U2 worker · U3 cliente audio · U4 wake cliente
  · U5 orbe sync · U6 saga-ctl). Ver unit-of-work.md + unit-of-work-dependency.md. Orden: U1 → U2+U3 → U4+U5 → U6.

> **INCEPTION Ciclo 4 CERRADA.** Toda la planificación/documentación lista. CONSTRUCTION (código) NO se hizo
> (pedido del usuario). Revisión con mente fría hecha: plan APROBADO + 1 cambio (wake worker→cliente) +
> consideraciones del vault (room agrega fricción al instalable; oportunidad de limpiar deuda D1).

### CONSTRUCTION Ciclo 4 — ACTIVA (2026-06-23, usuario aprobó cruzar el gate)
Per-Unit Loop. Orden: U1 → U2+U3 → U4+U5 → U6. Build&Test al final (incluye benchmark de latencia = NFR gate).

**U1 — Infra room** (en curso):
- [x] Functional Design — SKIP (sin modelos/lógica de negocio; infra + minteo JWT)
- [x] NFR Requirements / NFR Design — SKIP (extensiones opt-out; seguridad = constraint duro en el plan)
- [x] Infrastructure Design — SKIP (topología/readiness ya mapeada en Application Design; plegado al code-gen plan)
- [x] Code Generation — **Part 1 (plan) + Part 2 (código) HECHOS**. **PIVOT Docker→BINARIO NATIVO** (ver
  Build&Test abajo): el server corre como `~/.local/bin/livekit-server` (v1.13.1, tarball oficial, checksum
  verificado), NO Docker. `docker-compose.yml` ELIMINADO (muerto). `livekit.yaml` (server config: signaling
  loopback, udp_port 7882 único, node_ip por env NODE_IP), vc/config.py (carga .env.local + constantes
  LIVEKIT_*), orb/orb_server.py (GET /token mint JWT lazy), .env.local (keys generadas). Verif: py_compile OK,
  JWT round-trip OK, server nativo HTTP 200, auth API OK, /token end-to-end OK. Summary: construction/U1-infra-room/code/.
- [x] **U2 (worker modo room) — HECHO**. `lk/agent.py`: detección de modo (`console` en argv), wake
  server-side gateado a console (en room va al cliente U4), log de transporte, docstring. Conserva todo el
  cerebro IA + Win+Z + claude_llm. Verif: py_compile OK + `lk/agent.py start` registra worker contra
  ws://127.0.0.1:7880 y espera dispatch. Summary: construction/U2-worker-room/code/.
- [x] **U3 (cliente browser audio) — HECHO**. `orb.html`: SDK livekit-client 2.19.2 vendoreado
  (orb/vendor/livekit/), conexión al room por /token, mic publicado muteado con gate por estado SSE
  (rec→unmute), reproducción del TTS + unlock autoplay, CustomEvent('orbstate'). BUG cazado+arreglado:
  orb_server MIME `.mjs`. Summary: construction/U3-cliente-audio/code/.

#### Build & Test PARCIAL (integración en vivo U1+U2+U3) — 2026-06-23 ✅ ANDANDO
Validado en el browser REAL del usuario: **turno de voz completo (texto Shift+Enter Y voz Win+Z) responde por
voz**. Worker llega a `agent_state -> speaking`, LLM + TTS completos, ICE conecta por UDP. Esto resuelve de
fondo el bug del buffer del Ciclo 3 (room descarta frames con track detached).

**PIVOT crítico — Docker → binario nativo (causa raíz: Docker NAT rompe WebRTC local):**
- Síntoma: orbe clavado en "Pensando"; en logs `dtls timeout` + el job salía a los ~30s. El cerebro+TTS
  funcionaban (LLM respondía, TTS generaba audio) pero el MEDIA no se entregaba.
- Diagnóstico (server logs): el transporte WebRTC del worker/cliente daba `dtls timeout`. Probado en host-net
  (UDP bindeaba a interfaz equivocada) y bridge+publish (NAT de Docker rompe el handshake DTLS). Causa = Docker
  NAT sobre WebRTC en localhost.
- Fix: **sacar Docker.** `livekit-server` como binario nativo (tarball oficial v1.13.1, checksum SHA256 OK,
  en `~/.local/bin/`, fuera del repo). Config: signaling loopback (default LiveKit), `udp_port` único 7882,
  `node_ip` = IP LAN auto-detectada por env `NODE_IP` (LiveKit no bindea UDP a loopback nunca → el candidato
  debe ser la interfaz real; signaling sigue loopback → nadie externo se une). Resultado: ICE por UDP, 0 dtls
  timeout, voz andando.
- **Auditoría contra doc oficial (context7)**: server/worker/token/cliente usan las herramientas de LiveKit
  como mandan (AccessToken+VideoGrants verbatim, agent.py start, livekit-client SDK, config nativa). Pivot a
  nativo = recomendación oficial para local. No es frankenstein.

**Fixes aplicados en esta integración (commiteados):**
- `lk/agent.py`: BVC noise_cancellation gateado a console (BVC requiere LiveKit Cloud; en self-hosted tiraba
  error). Alternativa self-host = ai_coustics (anotada, no aplicada).
- `lk/agent.py`: migrado `RoomInputOptions` (deprecado) → `RoomOptions(audio_input=AudioInputOptions(...))` (API 1.6).
- `orb/orb_server.py`: MIME `.mjs` (el SDK ESM se servía como octet-stream).

**Deuda anotada (pulido, no blocker):** (1) volumen de la respuesta baja en call de voz = echo-cancellation
ducking del browser (ajustable); (2) el path de Win+Z (socket Unix + SSE) es glue propio, no primitiva LiveKit
(revisable con data channel/RPC o full client-side en U4); (3) evaluar ai_coustics si molesta el ruido.

- [x] **U6 (saga-ctl modo room) — HECHO** (start en vivo pendiente de usuario). REORDENADO antes de U4/U5
  (U4 = port más caro/riesgoso; el sistema ya anda con Win+Z). `vcctl.py` + `vc/config.py`: `_start_room()`
  (server nativo NODE_IP-auto + claude + orb + worker start + xdg-open), `_livekit_server_pids()` (stop baja
  el binario), `SAGA_TRANSPORT=room|console`. Verif: py_compile OK; `saga-ctl status/stop` OK (stop baja el
  binario sin tocar este claude); `start` lo confirma el usuario en vivo. Summary: construction/U6-saga-ctl/code/.
#### Build & Test — hallazgos en vivo (2026-06-23)
- **Dispatch RESUELTO** (commit 9ccd758): dispatch explícito por API (agent_name + saga-ctl crea el dispatch).
- **Voz end-to-end andando**, MUY rápida (chunks parciales al LLM). Texto Shift+Enter limpio.
- **Logging de eventos en el monitor** (pedido del usuario) — HECHO: `_event()` en lk/agent.py con prefijo `▎`
  para Win+Z (grabar/cortar/cancelar), SILENCIO detectado, PENSANDO/HABLANDO, listo, texto. Confirmado: anda.
- **RESUELTO — turnos perdidos + chopping + away a los 0s** (verificado en vivo: "todo funciona, no falló en
  ningún momento"). 3 fixes en lk/agent.py:
  - `preemptive_generation=False`: la preemptive gen de LiveKit arrancaba el LLM sobre transcripts parciales y
    lo cancelaba/reintentaba; con el LLM custom (bridge bloqueante) eso colgaba el turno (`claude prompt` sin
    `turn OK`). Flag OFICIAL de AgentSession.
  - `endpointing min_delay 2→3s` (max 4→5): menos chopping (frases con pausas no se parten). Config oficial.
  - away timer: el away disparaba "no entendí" a los 0s (timer stale del idle anterior). **DEUDA SALDADA**
    (2026-06-23): reemplazado `user_away_timeout` nativo + `session._set_user_away_timer()` (privado) por un
    timer PROPIO `asyncio.call_later`, VAD-aware (arma en Win+Z, cancela al `speaking`/`thinking`). Sin
    internals de LiveKit. Verificado en vivo (usuario: 3 casos OK). + el timeout pinta el orbe AMARILLO
    "No te entendí" (estado `error`), no el rojo `cancel`.
  - Commits: ver git (turn-handling fixes).
- **DESCUBRIMIENTO (→ Ciclo 5 agéntico)**: saga no hace acciones (hora/clima/Spotify) porque corre con
  `--setting-sources ''` (sin MCPs/tools) + prompt que desalienta tools. No es bug de Ciclo 4. Ver Ciclo 5.

- [x] **U5 (orbe sync) — HECHO** (verificado en vivo, usuario 10/10). `orb.html`: el browser mide el nivel
  REAL del track TTS (Web Audio AnalyserNode) → el orbe late con la voz (lo desbloqueó el modo room; en console
  era imposible). Suavizado de envolvente (ataque/release asimétrico) + techo de escala (no se infla) +
  desbloqueo de autoplay sin botón (gesto). Fallback sintético: nunca queda plano. Commit ed7620c.
  Artefactos AI-DLC: plans/U5-orbe-sync-code-generation-plan.md + U5-orbe-sync/code/generation-summary.md.
  Build&Test del ciclo: build-and-test/ciclo4-build-and-test.md (11 issues encontrados+resueltos, tabla).

#### Build & Test — robustez del turno de voz (2026-06-23, verificado 10/10)
- **CAUSA RAÍZ del chopping/no-respuesta**: `preemptive_generation` quedaba ON. El param top-level está
  DEPRECADO y se ignora cuando se pasa `turn_handling`; el default es `enabled: True` (verificado en el source
  livekit `turn.py:151`). Fix: ponerlo DENTRO de `turn_handling={"preemptive_generation":{"enabled":False}}`.
  Esto mata el multi-commit (LLM sobre transcripts parciales) que partía/cancelaba turnos.
- **Turn detector semántico** (`MultilingualModel`, español) en `turn_handling` + `min_delay 2.0`: anti-chopping.
- **Cancel mata el turno del daemon** (`claude_daemon.py`): al cancelar, mata el grupo entero (sin zombie/
  huérfano) y respawnea con `--resume` (contexto intacto). Antes drenaba → daemon ocupado.
- **Watchdog** (`_busy`, 18s) + **empty-cut** (rapid Win+Z sin hablar → amarillo al toque): destraban cuelgues.
- Lección: NO adivinar config de LiveKit — verificar campos contra el TypedDict + el source. Hubo churn por eso.

- [x] **Build & Test final — CERRADO**: benchmark de latencia (NFR gate) corrido y registrado
  (build-and-test/ciclo4-build-and-test.md): cerebro 2.2s + voz 0.3s ≈ 2.5s, NO regresó (la percibida ~4.5s
  incluye el min_delay 2.0 anti-chopping, decisión tuneable). NFR ✅.
- [x] **README / docs — ACTUALIZADOS** a modo room (default): `.claude/CLAUDE.md` (arquitectura room + gotchas
  room + obsoletos corregidos), `README.md`, `lk/README.md`, y `docs/` completo (architecture, turn-flow,
  operations, internal-api, code-guide, tech-debt-plan, README). Verificados contra código (agentes en paralelo).
- [x] **U4 (wake "hey saga") server-side — CÓDIGO GENERADO** (2026-06-23, en vivo PENDIENTE). REDEFINIDA: en
  el SERVER (sobre el track), NO en el cliente. Decisión del usuario: server-on-track reusando el wake Python
  (livekit.wakeword) en vez del port a onnxruntime-web (evita el frankenstein). Part 1 (plan) aprobado + Part 2
  (código) hecho. 4 archivos: `lk/wakeword.py` (+`WakeWordTrackDetector`: rtc.AudioStream del track → ventana 2s
  deque → `predict` en executor cada ~240ms → debounce → `_press`); `lk/agent.py` (import rtc + track_subscribed
  /barrido del mic → arranca el detector en room; console sigue con el detector local); `orb/orb_server.py`
  (`/token` agrega flag `wake`); `orb/orb.html` (wake ON → mic DESMUTEADO siempre, gate orbstate off). Verif:
  py_compile OK + import smoke OK + predict smoke (chunking 2s→0.002, 80ms→0.0, CHUNK_FRAMES=25=2s) ✅. Opt-in
  `SAGA_WAKE_ENABLED=1`, default OFF. Summary: construction/U4-wake-server/code/generation-summary.md.
  **Pendiente: validación EN VIVO del usuario** ("hey saga" → graba). Riesgos abiertos:
  dos consumidores del track (plan B FrameProcessor) · falsos positivos · privacidad mic continuo (mitigado opt-in).
  Commit 2c4bae1 (U4 + fixes browser-dup/dispatch-503).
- [x] **U7 (cleanup: LiveKit/room estándar ÚNICO) — HECHO** (2026-06-23, commit 53d9960, en vivo PENDIENTE).
  Decisión INCEPTION del usuario: room es el estándar, no negociable. ELIMINADOS: (1) transporte console
  (`SAGA_TRANSPORT=console`, bug del buffer + glue `_CONSOLE_MODE`); (2) flujo clásico (`VOICE_LIVEKIT=0`,
  máquina de turnos standalone `vc/app.py` + STT/TTS propios). Único configurable que queda: wake on/off
  (`SAGA_WAKE_ENABLED`) + Deepgram-o-fallback (sin key → faster-whisper+edge DENTRO del agente). BORRADOS:
  vc/audio.py, vc/stt.py, vc/tts.py, whisper_daemon.py. Adelgazados: vc/app.py (→ press+doctor), lk/agent.py
  (sin console/BVC), vcctl.py (start→_start_room, status room-only), vc/config.py (sin flags+huérfanas).
  CONSERVADOS (no romper): vc/runtime.py (hub compartido), wake_daemon.py/Vosk (DORMIDO, fuera de scope),
  fallback whisper/edge del agente, doctor. Verif: py_compile + import smoke + grep refs=0 + saga-ctl status
  room-only + saga --doctor OK. Net ~1300 líneas menos. Plan/summary: construction/U7-remove-console/.
  Mapeo de deps con grep ANTES de borrar (hallazgo: vc/app.py:main ES el emisor de Win+Z → adelgazado, no borrado).

> **CICLO 4 — CERRADO en lo sustancial.** U1+U2+U3+U5+U6 + dispatch + voz robusta + U4 (wake server) + U7
> (room estándar único, basura legacy eliminada). Todo verificado estáticamente + lo previo en vivo (10/10).
> Pendiente: validación en vivo del usuario de U4 (hey saga) + U7 (saga-ctl restart room-único).

### U7.1 — Terminar la limpieza de U7 (ABIERTA, 2026-06-23)
- **Disparador**: el bug del mic se cerró como ENTORNO (Brave/getUserMedia), NO código (ver DIAGNOSTICO-mic.md).
  El working tree se había revertido a U4 sobre esa hipótesis falsa. El usuario pidió re-revisar U7 antes de
  restaurarlo: que quede TODO limpio (sin código/proceso fantasma, sin race, buenas prácticas, sin frankenstein).
- **Re-revisión (3 agentes paralelos sobre worktree 53d9960)**: **arquitectura U7 = LIMPIA** (anti-frankenstein:
  cero edición de libs, cero internals privados de LiveKit, cero orquestación casera de audio, turn config
  impecable vs livekit-agents 1.6.0; deuda `_set_user_away_timer` SALDADA). U7 NO se rehace. **Pero la limpieza
  quedó incompleta** → unidad U7.1.
- **Punch-list** (ver plan): ALTA = tests/test_pure rota (importa vc.tts borrado) · tools/say.py roto · race del
  dispatch (`LK_CTL_SOCK.exists()` + socket stage→`_sock_up` + cleanup en shutdown) · doble dispatch (fuente
  única). MEDIA = huérfanas (is_goodbye/GOODBYE_KEYWORDS, WORD_ALIASES_PATH, WAKE_MAX_IDLE_TURNS) · `_node_ip`
  loopback silencioso. BAJA = comentarios/docs/TMP_FILES console-clásico stale · podar Vosk de DAEMONS.
- **Criterio resuelto**: `sounddevice` SE QUEDA (wake_daemon dormido + doctor) · `saga.py` VIVO (emisor Win+Z) ·
  glue Win+Z→RPC = deuda opcional fuera de scope · `wake_daemon.py` = dormido intencional, solo se poda de DAEMONS.
- **Stages**: Requirements = la punch-list (aprobada: "CLEANUP COMPLETO"). User Stories/App Design/Units/Functional/
  NFR/Infra = SKIP (cleanup brownfield, sin lógica/componentes nuevos). Code Generation (plan + ejecución) +
  Build&Test = EXECUTE. Plan: construction/plans/U7.1-cleanup-code-generation-plan.md.
- **Estado**: Code Generation Part 2 EJECUTADO + Build&Test estático CERRADO. 18 archivos, +135/-290.
  py_compile OK · `tests.test_pure` 11/11 VERDE (antes rota) · import smoke OK · grep refs=0 · verificador
  adversarial 0 blockers (dispatch fuente-única confirmado seguro). **Deuda nueva flageada** (fuera de scope,
  pase aparte): cadena muerta del clásico en `vc/runtime.py` (PID/LOCK/signal_stop/signal_cancel, 0 callers).
  **Pendiente**: commit (OK del usuario) + validación en vivo (`saga-ctl restart` + Win+Z).
- **FIX cold-start (Build&Test en vivo, 2026-06-24)**: validando, salió el bug 503-on-cold-start (PRE-EXISTENTE,
  no de U7.1): el server da el puerto de signaling HOT antes que el subsistema de agent-dispatch; en frío el
  worker registra en esa ventana → server envenenado ("no response from servers") hasta reiniciar ("1ra en frío
  falla, 2da anda"). Fix: gate `_dispatch_subsystem_ready()` (list_dispatch con timeout 2s) en `_start_room`
  paso 3.5, ANTES de lanzar el worker. **Verificado por mí** (corrí stop+start en frío total ×2): dispatch al
  primer intento (antes 6 retries+503), agente en room, socket creado. Falta solo el turno de voz (usuario).
- **U7.1 CERRADA (2026-06-24)**: turno de voz validado en vivo por el usuario ("anduvo 100%"). Doc alineada
  (token-dispatch stale corregido en README/code-guide/internal-api + gotcha cold-start agregado a CLAUDE.md).
  Threshold wake 0.05→0.08 (.env.local, gitignored). Commit **cf726f7** (NO pusheado). Build&Test CERRADO.
  Deuda viva para próximos ciclos: (a) U7.2 cadena muerta clásico en vc/runtime.py; (b) fine-tune wake con
  voz real (Ciclo 2 diferido); (c) `Executor shutdown` en el wake detector al bajar (lifecycle, menor);
  (d) push de la rama + PR a main; (e) Ciclo 5 agéntico (tools/MCPs).

### U7.2 — Limpieza cadena muerta del flujo clásico en vc/runtime.py (2026-06-24)
- **Disparador**: el usuario pidió cerrar de verdad sin una línea fantasma. Root-cause check: cadena PID/lock/
  SIGUSR del flujo clásico standalone (que U7 eliminó) quedó en runtime.py con CERO llamadores.
- **Verificado cero-callers (no de memoria)**: `pid_alive`, `_proc_starttime`, `self_identity`, `read_pid_from`,
  `read_recorder_pid`, `read_owner_pid`, `signal_stop`, `signal_cancel` + `PID_FILE`/`LOCK_FILE`. Borrados.
  TMP_FILES de vcctl: sacados `saga.pid/lock/abort/wav` (temps clásicos nunca creados en room).
- **Scope acotado a propósito**: NO toqué `cancel_handler`/streamer/`set_current_proc` (también dead pero
  ACOPLADOS al `set_current_proc` que claudecli llama vivo + al `_cancel` vivo) → su limpieza necesita tocar
  el path de cancel de claudecli (no runtime-testeable desde acá). Queda flageado (eventual U7.3).
- **Verificado por mí**: py_compile + tests.test_pure 11/11 + import smoke (runtime/claudecli/app/agent/vcctl)
  + grep refs=0 + `os`/`signal` siguen vivos en runtime + **boot en vivo** (stop+start: claude HOT, dispatch
  del server HOT, agente en room, ambos sockets). El daemon (claudecli→runtime) sigue sano.
- **Estado**: CERRADO. Commits `86b3d9a` (U7.2) + `bc2cdb6` (CI) pusheados. **PR #1 mergeado a `main`**
  (merge `01b7161`). CI (`.github/workflows/tests.yml`: py_compile + tests.test_pure en push/PR a main)
  ahora vive en main. Rama feature 100% mergeada. Deuda restante flageada: U7.3 (cancel_handler/streamer/
  set_current_proc, acoplado a claudecli).

### U8 — Dispatch consistente del agente (hardening del arranque, 2026-06-24) — CONSTRUCTION ACTIVA
- **Disparador**: bug "coin-flip del dispatch" — `saga-ctl start` deja al agente fuera del room de forma
  intermitente → Win+Z `FileNotFoundError`/`ConnectionRefusedError`. "A veces anda, a veces no."
- **Causa raíz MEDIDA** (no timing): worker en modo prod con `load_threshold=0.7` → se auto-marca
  `unavailable` cuando la CPU local cruza 0.7 → si `create_dispatch` cae en esa ventana → `503 no response
  from servers`. El load-shedding es para POOLS de workers; saga = 1 worker/1 usuario → no aplica.
  **El retry de 90s en vcctl.py (working tree sin commitear) es un PARCHE que U8 descarta** (no se commitea).
- **Diseño** (4 cambios nativos, ver `construction/U8-dispatch-consistente/functional-design.md`):
  C1 `AgentServer(load_fnc=lambda:0.0, drain_timeout=0)` (worker siempre disponible + stop sin draining-zombie)
  · C2 dispatch AUTOMÁTICO nativo (`@server.rtc_session()` sin agent_name + eliminar `_ensure_agent_dispatched`
  + `LIVEKIT_AGENT_NAME`) · C3 server+worker SIEMPRE frescos en `start` + reordenar (browser antes del
  wait-socket) · C4 `close_on_disconnect=False` (socket Win+Z sobrevive recarga de pestaña).
- **Stages**: Functional Design CERRADO · NFR/Infra/UnitDesign = SKIP · Code Generation Part 1 (plan) +
  **Part 2 (código) HECHOS** (aprobado por el usuario, condicional a la garantía de no-regresión).
  Código: `lk/agent.py` (load_fnc=0/drain_timeout=0/num_idle_processes=1 + auto-dispatch + pop env +
  close_on_disconnect=False), `vcctl.py` (eliminada `_ensure_agent_dispatched` → helper `_kill_pids`;
  `_start_room` server+worker frescos + browser→wait-socket, sin dispatch API; neto −150 líneas),
  `vc/config.py` (eliminada `LIVEKIT_AGENT_NAME`), `orb_server.py` (comentario). Docs: `.claude/CLAUDE.md`
  + 7 archivos (docs/*, README, lk/README). Step 0: tests.yml espurio revertido. Toda la API verificada
  contra livekit-agents 1.6.0 instalado (inspect/getsource), no de memoria. Summary:
  `construction/U8-dispatch-consistente/code/generation-summary.md`.
- **Verificación estática CERRADA**: py_compile TODO OK + import smoke + tests.test_pure 11/11 + grep refs
  muertas=0 en código. Análisis de impacto (grep): wake/orbe/turnos/LLM/STT FUERA del diff (no se rompen).
- **Build & Test EN VIVO — VALIDADO 100% por el usuario (2026-06-24)**: arrancó de 0, restart, uso real →
  NO se rompió, "funcionó bien". **Cold boot del SO COMPLETADO**: reinició toda la PC, saga levantó limpio,
  "funciona perfectamente, no hay errores, super consistente y prolijo". U8 CERRADO — sin pendientes.
- **Docu pendiente RESUELTA (2026-06-24)**: `docs/README.md` (puerta de entrada) estaba stale — describía
  "fallbacks console y clásico" (eliminados en U7) y no mencionaba el modo único room / dispatch automático.
  Corregido: ahora dice "modo único transporte ROOM + dispatch automático nativo". Era el único gap de la
  verificación de sincronización docs↔código (resto 100% alineado, U8 cubierto en 6/7 archivos → ahora 7/7).
- **Build and Test U8 — CERRADO OK** (2026-06-24). Commit + push autorizados por el usuario.

## ESTADO GLOBAL (2026-06-24)
**Ciclo 4 (console→room) CERRADO Y MERGEADO A MAIN** (PR #1, merge 01b7161). Incluye U1–U7 + U7.1
(limpieza + fix race/cold-start) + U7.2 (cadena muerta runtime) + CI. Doc 100% alineada. Validado en vivo.
**U8 — dispatch consistente CERRADO Y VALIDADO 100% EN VIVO** (hardening del arranque, causa raíz =
load_threshold; auto-dispatch nativo). Cold boot del SO OK. Docu de entrada (`docs/README.md`) alineada.
Mergeado a main (PR #2). Deuda menor: U7.3 (cancel/proc machinery), fine-tune wake (Ciclo 2
diferido), `Executor shutdown` del wake detector al bajar.

## U9 — Cap threads ONNX (CPU del wake) — CERRADO Y VALIDADO 10/10 (2026-06-24)
- **Problema**: worker a ~410% CPU en idle. Causa raíz (docs oficiales onnxruntime + entorno): ONNX abre
  1 thread/core y los hace SPIN (busy-wait) entre inferencias → el wake "hey saga" (modelo 169 KB, infiere
  ~cada 240ms) quemaba ~367% CPU con 50 threads sin computar.
- **Fix**: `lk/onnx_tune.py` `cap_onnx_threads()` parchea `ort.InferenceSession` (intra/inter=1 +
  `session.intra_op.allow_spinning=0`), llamado en `agent.py` antes de cargar modelos. Idempotente +
  degradación segura. `OMP_NUM_THREADS` descartado (onnxruntime 1.26 sin OpenMP → única vía SessionOptions).
- **Resultado MEDIDO en vivo**: CPU worker **410% → 40%** (10x). Wake 367%/50thr → 3.5%/1thr. RAM 2757→2441 MB.
  Detección intacta (usuario 10/10: "me detecta la voz igual, no veo fallos"). Sin tocar features.
- **Fuera de scope**: RAM del turn detector semántico (~1.8 GB) = fix C (turn detector → VAD puro), otro ciclo.
  Split Pi (browser/mic vs worker) + onnxruntime-web para el wake = deploy hardware chico, futuro.
- **Mergeado a main** (PR). Ciclo 5 (tools/MCPs) sigue ABORTADO/diferido (el spike mostró boot storm + ROI dudoso).

## Ciclo 5 — saga agéntico (cargar plugins en Claude) — **CERRADO (2026-06-25)**
> **CERRADO Y VALIDADO EN VIVO.** Spike completo: medición A/B (off vs full) + auditoría + 2 bugs hallados.
> **Veredicto:** cargar plugins FUNCIONA; con blacklist agresiva (4 MCPs) el overhead es +1-2s/turno (tolerable,
> vs 10x del full completo). saga YA es agéntica con built-ins (en `off` respondió "último partido de la
> selección" vía WebSearch, sin plugins). **Decisión del usuario:** deja los plugins activos por ahora
> (`VOICE_FULL_STACK=1` en `.env.local`) — "me gustan, los MCPs son prácticos"; el DEFAULT del código sigue
> `0` (reversible). **PENDIENTE (futuro):** definir qué plugins/MCPs son realmente útiles para saga según su
> propósito (el usuario lo va a meditar). **Bug arquitectónico abierto:** TTS de Deepgram timeoutea en
> respuestas largas con tools (pausas matan el stream) → fix = frankenstein, NO se hizo.
>
> **Entregables (código, sin commitear aún — pendiente OK del usuario):** toggle `VOICE_FULL_STACK` (master
> switch env) + blacklist `configs/plugins-blacklist.json` (17 baneados) + `tools/measure_stack.py` (atribución
> RSS/CPU/TTFT) + watchdog `_PROC_TIMEOUT` 18→60s + `load_dotenv` movido al top de config.py (las `VOICE_*`
> ahora viven en `.env.local`). Todo reversible, default off.
>
> --- histórico ---
> El spike previo (`VOICE_FULL_STACK`) fue ABORTADO + REVERTIDO (boot storm sobre worker saturado, pre-U9).
> Re-abierto tras U9/U10. El toggle ya NO existía en el código (cero refs) → se reimplementó.

### Reality-check (registrado en requirements)
- **U9 ≠ fix del boot storm.** U9 capeó CPU del WORKER (wake ONNX). El boot storm venía de los MCPs pesados
  del STACK DE CLAUDE (`claude_daemon`, otro proceso: playwright/Chromium, npx, Google MCPs timeout). Cargas
  ORTOGONALES → el ciclo MIDE, no asume. Costos permanentes: arranque daemon más lento (~7s→~57s) + tool-defs
  por turno en contexto.

### INCEPTION Ciclo 5
- [x] Workspace Detection — RESUME (brownfield)
- [x] **Requirements Analysis — COMPLETO Y APROBADO** (ciclo5-agentic-requirement-questions.md +
  ciclo5-agentic-requirements.md). Decisiones: Q1=A (spike de medición primero) · Q2=C resuelto
  (full-stack-first como INSTRUMENTO; lista curada de plugins viables = ENTREGABLE, no input) · Q3=A (toggle
  reversible default OFF, **por ENV** — confirmado al usuario: es el patrón de toda la config de saga) · Q4=C
  (gate estabilidad + latencia, abort si rompe) · Q5 (seguridad mínima: god-mode + `vc/guard.py` + regla en prompt).
  **Hallazgo Q5**: el plugin borrado era **safety-net** (v0.8.2, marketplace cc-marketplace) = PreToolUse Bash
  hook anti-destructivo; **saga ya lo replica en `vc/guard.py`** → re-descargar = redundante. Gap real = tools
  MCP no-Bash (efectos externos) que el guard no intercepta.
  Extensiones: Security/Resiliency/PBT = **No** (ver Extension Configuration).
- [x] **Workflow Planning — COMPLETO Y APROBADO** (execution-plan-ciclo5.md). Stages a ejecutar: Code
  Generation + Build&Test. SKIP: User Stories / App Design / Units / Functional / NFR Req / NFR Design /
  Infra (spike de config single-component). Riesgo Low (código) / Medium (boot storm en vivo). Reversible
  (default OFF). Ajustado tras objeción del usuario: + observabilidad de ATRIBUCIÓN (FR3.1/FR3.2).

### CONSTRUCTION Ciclo 5
- [x] Functional/NFR Req/NFR Design/Infra Design — SKIP (sin lógica/modelos/infra nuevos).
- [x] **Code Generation Part 1 (plan) — COMPLETO** (construction/plans/ciclo5-code-generation-plan.md).
  5 pasos: (1) toggle granular `VOICE_FULL_STACK` off/full/selective en `vc/config.py`; (2) log del modo;
  (3) harness `tools/measure_stack.py` (RSS/CPU por MCP + TTFT del saga.log); (4) doc operativo de la prueba;
  (5) verificación estática. Hallazgo clave: el daemon hereda env (`prewarm_claude` env={**os.environ}) →
  vcctl/daemon NO se tocan; cambio aislado a config + 1 script. Reversible (default OFF idéntico al actual).
- [x] **Code Generation Part 2 (código) — HECHO** (REVISADO en Build&Test tras 2 objeciones del usuario).
  Modelo final = toggle `VOICE_FULL_STACK` off/full + granularidad **a NIVEL PLUGIN** (no MCP). (1)
  `vc/config.py`: `VOICE_DISABLED_PLUGINS` (csv, default playwright) → `.saga-settings.json` con guard +
  `enabledPlugins:false`, inyectado por `--settings` SOLO al daemon (PER-SAGA, NO toca `~/.claude/settings.json`).
  Descartado el modelo MCP-only (`--strict-mcp-config`/`.mcp-selective.json`): unidad equivocada. `.guard-settings.json`
  → renombrado `.saga-settings.json` (gitignore actualizado). (2) `claude_daemon.py`: log `stack=` + `off=<plugins>`.
  (3) `tools/measure_stack.py` (RSS/CPU por MCP + TTFT). (4) doc `how-to-measure.md`.
  **VERIFICADO el mecanismo en vivo**: `--settings enabledPlugins:false` saca el plugin de `claude mcp list`
  per-sesión (playwright 1→0). **Estática VERDE**: py_compile · flags off/full correctas · `.saga-settings.json`
  bien formado (guard+enabledPlugins) · override `VOICE_DISABLED_PLUGINS=""` ok · import daemon · tests 11/11.
  **CORRECCIÓN registrada**: deshabilité playwright GLOBAL por error (`claude plugin disable`, scope user) →
  REVERTIDO (`enable`, vuelve a true); el control quedó a nivel código/env de saga, como pidió el usuario.
- [ ] **Gate de aprobación de Code Generation (revisado) — PENDIENTE** (usuario).
- **Comparativa de recursos (medida)**: off=2 procs/240 MB · full−17baneados=6 procs/643 MB · full=11 procs/1044 MB.
  TTFT: off ~1.5s (baseline) · full−17 sin tool 4-6s, con tool 9-26s · full sin tool 13-17s. La carga de plugins
  cuesta latencia (contexto inflado por tool-defs); con tool, además, round-trips irreducibles.
- [x] **Build & Test — CERRADO (validado en vivo, A/B + auditoría)**. Flujo validado END-TO-END (restart sin inline → toma `stack=full`
  desde `.env.local`; `off=playwright` desde la blacklist JSON; árbol del daemon 11 procesos sin playwright).
  Sin boot storm (load 2.5/8, CPU ~1%); stack ~1.04 GB (claude 247, context7 199, mcpvault 190, exa 188,
  claude-mem 122). **TTFT en full (señal preliminar)**: primer turno `ttft=5.592s` vs ~1.4-2s normal stripped
  → el stack infla el TTFT (tool-defs en contexto), como se predijo; un turno siguiente dio 0.47s (corto).
  Falta confirmar el patrón con más turnos de voz del usuario + ver si saga usa tools.
- **Fix colateral (bug que destapó el usuario)**: `.env.local` se cargaba DESPUÉS de leer las `VOICE_*`
  → no se podían setear ahí. Movido `load_dotenv` al TOP de config.py → ahora todas las `VOICE_*` viven en
  `.env.local`. `VOICE_FULL_STACK=1` agregada ahí. Verificado: STACK_MODE=full sin inline; LIVEKIT keys OK.
- **BUG REAL hallado (Build&Test, systematic-debugging)**: el watchdog `_busy` (lk/agent.py:206,
  `_PROC_TIMEOUT=18.0`) mata turnos con tool/MCP con "no te entendí" — no distingue colgado de trabajando.
  Causa agravante: full stack lleva el TTFT de ~1.5s (stripped) a **13-17s** (~10x) por tool-defs en contexto;
  turnos con tool suman round-trips → cruzan 18s. Fix ideal a futuro = condition-based (heartbeat/tool_use
  resetea el watchdog). **APLICADO (decisión del usuario, pragmático): `_PROC_TIMEOUT` 18→60s** (lk/agent.py),
  red de seguridad para cuelgues reales, no presupuesto de latencia (el daemon corta a 180s). py_compile OK +
  CLAUDE.md gotcha actualizado. Validación en vivo pendiente.
- **Reducción de carga (1er experimento)**: blacklist ampliada a **17 plugins** (deja solo github +
  claude-obsidian). Árbol del daemon **11→6 procesos**, RAM **1044→637 MB (−40%)**. Quedan exa-mcp + mcpvault
  (obsidian) = MCPs STANDALONE (no plugins → la blacklist no los toca); github es HTTP remoto (sin proceso).
  TTFT post-reducción = pendiente (turno de voz del usuario). Si sigue >18s con tool → hace falta el fix del watchdog.
- [x] **REDISEÑO del control de plugins (3x, por el usuario) — HECHO**. Modelo final: env `VOICE_FULL_STACK`
  = master switch (0=claude a secas / 1=stack) + blacklist **`configs/plugins-blacklist.json`** (editable,
  `{"disabledPlugins": ["name@marketplace", ...]}`, escala a N). **Sacado el hardcode** `_DEFAULT_DISABLED` y la
  env-csv `VOICE_DISABLED_PLUGINS`. JSON elegido sobre txt (coherente con el formato nativo de Claude Code
  `enabledPlugins`; el destino `.saga-settings.json` ya es json → cero conversión). Verificación estática VERDE
  (parser ignora `_comment`, degrada a [] si JSON roto, flags off/full, `.saga-settings.json` bien formado,
  tests 11/11). Falta restart para aplicar el nuevo código.

### Spike (a reimplementar en Construction)
- Toggle env reversible (default OFF) en `vc/config.py` que saltea `--setting-sources ''` → carga el stack.
- Instrumentación reusada (NO se agrega): boot del daemon (`claude_daemon.py`); TTFT/turno (`lk/agent.py` → `saga.log`).
- MCPs que cargaría el full stack: Gmail, Google Calendar/Drive, exa, monton, obsidian-vault, claude-mem,
  context-mode, context7, github, playwright, vercel. Pesados/externos: playwright, Google*, github, vercel.

## Ciclo 3 — Fix buffer de audio + feedback "no hay voz"
- **Tipo**: bugfix + enhancement UX, brownfield. RE vigente → skip RE.
- **Problema**: el mic acumula audio en idle (set_audio_enabled no detiene la captura en console) → al
  abrir, backlog de ~121s → VAD/away se ahogan → orbe pegado en "Grabando".
- **Decisiones** (2026-06-23, ver buffer-fix-requirement-questions.md):
  - Q1 mecanismo: `clear_user_turn()` (nativo). pause/resume DESCARTADO (API interna peligrosa).
  - Q2 feedback: SÍ, amarillo "No te entendí" (estado `error` del orbe) cuando no hay voz.
  - Q3 scope: reactivar wake al final + validar en vivo.
- **Restricción dura**: NO tocar buffers/streaming a mano. Solo API/config nativa LiveKit.

### INCEPTION Ciclo 3
- [x] Workspace Detection / Reverse Engineering — reutilizados (brownfield vigente)
- [x] Requirements Analysis — COMPLETO (buffer-fix-requirement-questions.md)
- [x] User Stories / Application Design / Units Generation — SKIP (bugfix acotado, entregable único)
- [x] Workflow Planning — execution-plan-ciclo3.md

### CONSTRUCTION Ciclo 3
- [x] Functional/NFR/Infra Design — SKIP
- [x] Code Generation — se intentó (clear_user_turn reordenado, reset away timer, amarillo error)
- [x] Build and Test — **REVERTIDO. Diagnóstico = entregable del ciclo.**
  - **Resultado**: los parches NO resolvieron y empeoraron el flujo (cada fix tapaba un borde y el backlog
    abría otro: away prematuro, "Pensando" colgado con audio vacío, respuestas a ruido fantasma).
  - **Decisión del usuario (2026-06-23)**: ROLLBACK. `git checkout lk/agent.py lk/claude_llm.py` al commit
    estable 4743056. Sin parches del Ciclo 3, sin orbe amarilla. Wake queda ACTIVO (la detección "hey saga"
    anda bien; lo que falla es el flujo post-captura por el buffer).
  - **CAUSA RAÍZ (firme, verificada 3x + research)**: en modo console `set_audio_enabled(False)` NO detiene
    la captura → el `rtc.AudioStream` (livekit-core C++) acumula audio en idle (backlog medido: 72s, 23s,
    12s, 4.7s — intermitente). El buffer es OPACO: no se purga desde Python. `clear_user_turn` no alcanza.
    Con backlog, el STT transcribe ruido como texto fantasma → flujo roto.
  - **FIX REAL (Ciclo futuro)**: salir del modo console. Opciones a investigar: (a) otro modo de LiveKit
    (worker/room real) donde el input track se conecta/desconecta de verdad; (b) capturar la consulta con
    stream propio (portaudio, como el wake y el modo viejo) + STT, sin pasar por el pipeline de audio de
    LiveKit en console. Es rearquitectura, no parche.
  - **Estado actual**: código = commit estable. Wake ACTIVO (`SAGA_WAKE_ENABLED=1`). Limitación del buffer
    conocida y documentada. Win+Z andando.

## Ciclo 2 — Wake word "hey saga" (ENTREGADO 2026-06-23)
- Feature implementada + modelo (FPPH=0) + docs, **commiteado y pusheado** (commit 4743056).
- Wake OFF por default: bloqueado por el bug del buffer → se resuelve en Ciclo 3.

## Ciclo 2 — Wake word "hey saga"
- **Tipo**: feature, brownfield. RE vigente (ciclo 1) → skip RE.
- **Problema**: Vosk = falsos positivos masivos. Evaluar alternativa.
- **Research hecho**: livekit-wakeword (recomendado, nativo a LiveKit, 100× menos falsos+ que openWakeWord), openWakeWord (plan viejo), Porcupine (cerrado), microWakeWord (ESP32/futuro).
- **Decisiones tomadas** (2026-06-22):
  - Engine wake: livekit-wakeword (pre-decidido)
  - Mic: toggle/opt-in (B) — Win+Z sigue primario
  - ~~Training: synthetic-only (A)~~ → **CORREGIDO post-Build&Test: synthetic positives (VoxCPM) +
    ACAV100M real negatives (2000h)**. Synthetic-only falló (falsos+ masivos por falta de negativos reales).
  - Frase: "hey saga" (A)
  - Speaker verify: diferido a Ciclo 3 (B)

### INCEPTION Ciclo 2
- [x] Workspace Detection — reutilizado de Ciclo 1
- [x] Reverse Engineering — reutilizado de Ciclo 1 (brownfield, vigente)
- [x] Requirements Analysis — Completo 2026-06-22 (Q2=B, Q3=A, Q4=A, Q5=B, Q1 diferido C3)
- [ ] User Stories — SKIP (feature pequeña, sin ambigüedad de scope)
- [x] Workflow Planning — Aprobado 2026-06-22 (execution-plan-ciclo2.md)
- [ ] Application Design — SKIP (sin componentes/servicios nuevos)
- [ ] Units Generation — SKIP (entregable único)

### CONSTRUCTION Ciclo 2
- [x] Functional Design — SKIP (hook directo wake→press, sin lógica compleja)
- [x] NFR Requirements — SKIP (extensiones off)
- [x] NFR Design — SKIP
- [x] Infrastructure Design — SKIP (pip package local, sin cloud)
- [x] Code Generation — Completo 2026-06-22 (lk/wakeword.py NEW · lk/agent.py MOD · scripts/train_wakeword.py NEW · pyproject.toml MOD)
- [x] Build and Test — **CERRADO OK 2026-06-22**. Iteración final (piper positives + ACAV100M 2000h real):
  **FPPH=0.00, Recall=98.5%, AUT~0** (validación 17.27h, 31k negativos reales). Verificado en vivo: 0 falsos
  positivos en 60s de ambiente (el modelo synthetic-only flasheaba cada 2s). Wake habilitado
  (`SAGA_WAKE_ENABLED=1`, `SAGA_WAKE_THRESHOLD=0.5`). Beep de feedback cableado. Pendiente: confirmación en
  vivo del usuario que su voz dispara el wake (la mitad cross-speaker que requiere hablar).
  - Iteraciones: (1) piper sin ACAV → FPPH 54; (2) VoxCPM sin ACAV → scores solapados; (3) VoxCPM+ACAV →
    abortada (VoxCPM 51s/clip en CPU = 71h inviable); (4) **piper+ACAV → FPPH 0, ganadora**.
  - Nota técnica: VoxCPM (difusión) inviable en CPU sin GPU. piper positives = misma calidad efectiva porque
    el fix real son los negativos reales (ACAV), no el TTS. Es la receta canónica de openWakeWord pre-trained.
  - **Validación en vivo (usuario)**: 0 falsos positivos (excelente), PERO recall marginal en la voz del
    usuario — scores 0.06-0.13, requiere estar cerca del mic. Causa: positivos sintéticos (voces inglesas)
    no cubren bien el acento rioplatense. Threshold estable = 0.06 (a 0.04 flashea).

### CONSTRUCTION Ciclo 2 — Debug en vivo (2026-06-22 noche)
Síntomas reportados: orbe pegado en "Grabando", wake "solo si hablás lento", scores bajos.
**Causa raíz (verificada en log)**: el mic de laptop capta ruido de fondo continuo (STTMetrics de 5s
ininterrumpidos por ~90s). El silero VAD (activation_threshold 0.5) lo veía como voz → nunca detectaba
silencio → el turno no cerraba → orbe pegado en rec (reflejaba la realidad: SÍ seguía grabando). El mismo
ruido degrada los scores del wake y obliga a hablar lento/claro. NO era la voz, el acento ni el modelo.
Fixes aplicados:
- `lk/agent.py`: `silero.VAD.load(activation_threshold=0.6)` — filtra el ruido de fondo.
- `lk/agent.py`: watchdog de grabación (REC_TIMEOUT=6s) — si entrás en rec y no hablás, vuelve a idle solo
  ('no entendí'). Recupera comportamiento del flujo clásico + red de seguridad anti-orbe-colgado.
- `lk/agent.py`: log de `agent_state_changed` (debug de la máquina de estados).
Otros hallazgos: TTS APITimeoutError (Deepgram, transitorio de red); el "orbe blanco" es el estado rec
normal (núcleo brillante por diseño), no un bug de render.
Pendiente: validación en vivo del usuario (orbe vuelve a idle en los 2 casos).

### BUG ABIERTO — buffer de audio acumulado en idle (modo console LiveKit)
**Severidad**: alta (bloquea el wake en uso real). **Estado**: diagnosticado, sin fix.
**Síntoma**: al disparar el turno (wake o Win+Z), el orbe queda "Grabando" indefinidamente; el VAD/away
tardan o no cierran; saga responde pero el flujo no vuelve a idle.
**Causa raíz (confirmada en log + código)**: en modo console, `session.input.set_audio_enabled(False)`
NO detiene la captura física del mic — el audio se sigue acumulando en un buffer durante el idle. Al abrir
el mic, LiveKit entrega TODO el backlog de una (medido: audio_duration=121s tras 123s en idle; 40s, 23s,
13s en otros casos — el nº coincide con el tiempo en idle). El VAD y el `user_away_timeout` no pueden
detectar "silencio actual" mientras procesan minutos de audio viejo → el cierre se ahoga.
**Lo que NO lo arregla** (ya probado): subir VAD activation_threshold (0.5→0.6→0.7, ayuda con ruido vivo
pero no con el backlog); `user_away_timeout=6.0` nativo (no cuenta mientras procesa el backlog); watchdog
manual (causó session_error por race, revertido).
**Pistas para el fix** (research previo): `clear_user_turn(stt_flush_duration=...)`, el "pre-connect audio
buffer" en room_io/_input.py (líneas 340-357), `on_attached/on_detached` del audio_stream según
audio_enabled (io.py:442-462). Hipótesis: en console el track no se detacha físicamente; habría que
descartar el buffer al entrar en rec, o cambiar cómo se controla el mic (conectar/desconectar el track
real en vez de set_audio_enabled). Requiere research dedicado de la API console de LiveKit.
**NFR**: el fix NO debe tocar el pipeline de streaming a mano (decisión del usuario) — usar mecanismos
nativos de LiveKit.

### Fixes aplicados esta sesión (quedan, son mejoras válidas)
- `lk/agent.py`: `_WAKE_ENABLED` — bug `bool("0")==True` arreglado (SAGA_WAKE_ENABLED=0 ahora apaga de verdad).
- `lk/agent.py`: VAD `activation_threshold=0.7` (filtra mejor el ruido del mic de laptop).
- `lk/agent.py`: `user_away_timeout=6.0` nativo + handler `user_state_changed -> away` (vuelve a idle si no
  hablás). Funciona parcialmente; limitado por el bug del buffer.
- `lk/agent.py`: log de `agent_state_changed` (debug; se puede quitar cuando se cierre el bug).

### Estado del wake (fin de sesión 2026-06-22 noche)
Wake **DESHABILITADO** (`SAGA_WAKE_ENABLED=0`). Win+Z es el trigger. El modelo `hey_saga.onnx` (FPPH=0,
ACAV) queda entrenado y listo; el blocker para activarlo es el bug del buffer, NO el modelo.

### CONSTRUCTION Ciclo 2 — Sub-iteración: fine-tune con voz real (DIFERIDO)
> Diferido: el cuello de botella real resultó ser el buffer de audio + ruido de mic, no el recall del
> modelo. El fine-tune con voz real sigue siendo válido (sube recall + alimenta Ciclo 3) pero se retoma
> DESPUÉS de resolver el bug del buffer. Script de grabación `scripts/record_wakeword.py` ya está listo.
- **Decisión usuario (2026-06-22)**: encarar fine-tune con grabaciones reales. Doble propósito: (a) sube el
  recall del wake en la voz del usuario (0.06 → ~0.8+); (b) las mismas grabaciones alimentan speaker
  verification (Ciclo 3) — sin trabajo duplicado.
- **Channel matching**: grabar con el mismo mic de uso (laptop), distancia real, variando condiciones.
- [x] Code Generation — `scripts/record_wakeword.py` (graba N muestras 16kHz mono, resume, guía de variación,
  feedback de nivel). Compila + smoke OK (mic abre a 16kHz nativo).
- [ ] Grabación — PENDIENTE (requiere al usuario: correr el script y hablar). No automatizable.
- [ ] `scripts/finetune_wakeword.py` — PENDIENTE (mezclar grabaciones + dataset, reentrenar).
- [ ] Reentrenamiento + validación en vivo.

## Execution Plan Summary
- **Total Stages**: 13 (5 INCEPTION hechas/decididas, Construcción definida)
- **Stages to Execute**: Code Generation (=> archivos `docs/`), Build and Test (=> verificación de doc)
- **Stages to Skip**: User Stories, Application Design, Units Generation, Functional Design,
  NFR Requirements, NFR Design, Infrastructure Design — todas N/A para un entregable de
  documentación sin cambios de código. Operations = placeholder.

## Backlog / Ciclos futuros

### Ciclo (futuro) — saga como servicio de voz HEADLESS / LAN (NO encarar TODAVÍA, 2026-06-24)
> **Decisión del usuario: NO tocar ahora.** Hoy saga vive DENTRO de su PC (asistente de escritorio) y así
> está perfecto. Esto queda documentado para el día que se quiera correr en una mini PC / Raspberry Pi 24/7.
- **Por qué NO sale "tal cual está"** (verificado en código, 2026-06-24): dos supuestos rompen la premisa de
  "mini PC headless con mic":
  1. **El mic lo lee el BROWSER, no el server.** `lk/wakeword.py` consume el `rtc.AudioStream` del track que
     publica el browser (getUserMedia). Ningún proceso de saga lee hardware de audio. Sacar el monitor ≠ sacar
     el browser: el browser es el DISPOSITIVO DE AUDIO (mic in + TTS out), no solo la UI del orbe.
  2. **Todo bindeado a loopback A PROPÓSITO** (privacidad/seguridad): LiveKit signaling `bind_addresses:
     127.0.0.1` (`livekit.yaml`), `orb_server` en `127.0.0.1`, y el `/token` devuelve `ws://127.0.0.1:7880`.
     "Conectarse desde otra PC de la LAN" NO sale sin reconfigurar esos 3 binds + el token + sumar AUTH (hoy
     el loopback ERA la seguridad → exponerlo abre el room a cualquiera de la red).
- **Dos escenarios viables** (elegir cuando se encare):
  - **A — mini PC = backend; browser+mic+parlantes en otra PC de la LAN.** Falta: exponer signaling+orb_server
    a `0.0.0.0`, token con IP real de la mini PC, AUTH de red. El mic/parlante son los de la PC cliente.
  - **B — mini PC = todo; hablarle a su mic físico, headless.** Falta: browser kiosk corriendo EN la mini PC
    (display virtual Xvfb + audio Pipewire + autostart) que abra el orbe local. Ahí el loopback alcanza.
- **Transversal a ambos (capa de servicio que hoy NO existe)**: supervisión de procesos (systemd units +
  `Restart=always` + arranque al boot + watchdog/healthcheck que reinicie la pieza muerta), rotación de logs
  (`saga.log` crece infinito), y en ARM/RPi **Deepgram OBLIGATORIO** (faster-whisper+onnxruntime en CPU ARM =
  inusable) + validar wheels ARM de los plugins. Wake word con deuda abierta (Executor-shutdown al bajar +
  recall marginal rioplatense 0.06-0.13) → no confiable como trigger 24/7 sin fine-tune.

### Orbe — sync real con audio TTS
- **Problema**: animación actual es sintética (audioLevel falso por estado), no refleja el audio real.
- **Intentado**: metering RMS → POST /level → SSE → browser. Descartado: lag inevitable HTTP entre pacat y browser.
- **Opciones viables**:
  1. **Electron/Tauri** (desktop app): acceso a Web Audio API nativa + AnalyserNode sobre audio del sistema. Sync perfecto. Cambio arquitectónico grande — app de escritorio en vez de browser.
  2. **Browser como participante LiveKit**: el orbe se conecta al room LiveKit y recibe el track TTS de audio. Usa AnalyserNode directamente sobre el track. Factible dentro del stack actual, trabajo considerable.
- **Decisión 2026-06-22**: ambas opciones consideradas. Se mantiene browser por ahora. Electron/Tauri queda como posibilidad futura si la app crece a desktop completo. Opción 2 es el camino preferido si se implementa dentro del stack web.

## Workspace State
- **Existing Code**: Yes
- **Programming Languages**: Python 3.12 (28 archivos .py), JavaScript/HTML (orbe Three.js)
- **Build System**: setuptools (pyproject.toml) + lock pip (requirements.txt)
- **Project Structure**: Monolito modular (paquete `vc/` + paquete `lk/` + daemons de raíz + orbe web)
- **Reverse Engineering Needed**: Yes
- **Workspace Root**: /home/renzo/.local/share/saga

## Code Location Rules
- **Application Code**: Workspace root (NUNCA en aidlc-docs/)
- **Documentation**: aidlc-docs/ solamente
- **Structure patterns**: ver code-generation.md Critical Rules

## Extension Configuration

### VIGENTE — Ciclo 9 (2026-07-13). Cambio de postura: Security y PBT pasan a BLOQUEANTES.
| Extension | Enabled | Enforcement | Decided At |
|---|---|---|---|
| Security Baseline | **Sí** | Blocking (15 reglas) | Requirements Analysis Ciclo 9 (Q1=A) |
| Property-Based Testing | **Sí** | Blocking — modo FULL (PBT-01..10, no partial) | Requirements Analysis Ciclo 9 (Q2=A) |
| Resiliency Baseline | No | — | Requirements Analysis Ciclo 9 (Q3=B) |

> Reglas completas CARGADAS: `security-baseline.md` + `property-based-testing.md`. `resiliency-baseline.md` NO cargado.
> Decisión del usuario: el framework ahora es standard y se usa antes/durante cada desarrollo → seguridad y
> testing dejan de ser opt-out. A partir del Ciclo 9, todo stage debe presentar compliance summary de
> SECURITY y PBT; el incumplimiento de una regla APLICABLE es blocking finding (no se cruza el gate).

### Histórico (Ciclos 1–8) — opt-out
| Extension | Enabled | Decided At |
|---|---|---|
| Security Baseline | No | Requirements Analysis |
| Resiliency Baseline | No | Requirements Analysis |
| Property-Based Testing | No | Requirements Analysis |

> Notas: las tres se saltan como gate bloqueante (scope = documentación + plan, sin código nuevo).
> Security y PBT-partial quedan cubiertos como *recomendaciones* en el plan de remediación.
> Reglas completas de extensiones NO cargadas (todas opt-out).
> **Ciclo 8 (2026-07-12): re-confirmado por opt-in explícito** (delegado al AI) → Security=B(No),
> Resiliency=B(No), PBT=C(No). Justificación en ciclo8-cleanup-requirements.md: el ciclo BORRA código
> muerto, sin superficie de red/auth/secretos ni funciones puras/serialización nuevas. Compliance
> summary del ciclo: las 3 = **N/A** (no aplican al cleanup), no bloquean.

## Stage Progress

### INCEPTION
- [x] Workspace Detection — Completado 2026-06-21T22:49:10Z
- [x] Reverse Engineering — Aprobado 2026-06-21T22:49:10Z (review delegada; 1 fix aplicado)
- [x] Requirements Analysis — Completo 2026-06-21T22:49:10Z (User Stories incluido por pedido del usuario)
- [x] User Stories — **SKIPPED** por decisión del usuario (tarea de documentación; las historias agregaban ceremonia sin payoff). Artefactos de planning quedan como histórico, sin uso.
- [x] Workflow Planning — Aprobado 2026-06-21T22:49:10Z (alcance docs/ = FULL, 7 archivos)
- [ ] Application Design — **SKIP** (no hay componentes/servicios nuevos)
- [ ] Units Generation — **SKIP** (sin descomposición; entregable único)

### CONSTRUCTION
- [ ] Functional Design — **SKIP** (sin lógica/modelos nuevos)
- [ ] NFR Requirements — **SKIP** (extensiones opt-out)
- [ ] NFR Design — **SKIP**
- [ ] Infrastructure Design — **SKIP** (sin infra)
- [x] Code Generation — Part 1 aprobado (review delegada) + Part 2 generado: 7 archivos `docs/` + link en README + resumen. Esperando aprobación del entregable.
- [ ] Build and Test — **EXECUTE** → verificación de la documentación (siguiente)

### OPERATIONS
- [ ] Operations — PLACEHOLDER (fuera de scope)

## Reverse Engineering Status
- [x] Reverse Engineering (v1) - Completado y aprobado 2026-06-21T22:49:10Z (STALE — describía modo console + flujo clásico)
- [x] Reverse Engineering (REFRESH) - **CERRADO 2026-07-12** (8/8 artefactos). Refresh de artefactos 2026-07-11
  (7/8) + code-quality-assessment refrescado 2026-07-12 + auditoría de consistencia de los 7 contra código real
  (HEAD 57399b3): drift corregido en api-documentation (is_goodbye/vc.tts), component-inventory
  (WakeWordTrackDetector ubicación, /events vs /state, sound.py vivo, test_pure real, say.py→measure_stack),
  technology-stack (CI existe, wake en worker), business-overview (wake en worker), dependencies (vc/app.py NO
  es stub). architecture + code-structure = 100% consistentes sin cambios. Motivo del refresh: v1 obsoleto tras
  Ciclo 4 (room), U7 (borra console/clásico), U8 (dispatch auto), U9 (cap ONNX), U10 (VAD puro), U11 (CLAUDE_PLUGINS).
- **Artifacts Location**: aidlc-docs/inception/reverse-engineering/

## Doc-sync 2026-07-12 — CERRADO
Objetivo: documentación de TODO el proyecto consistente con el código actual (HEAD 57399b3, U11).
- **docs/ (7 archivos + READMEs + CLAUDE.md)**: auditados contra código. Veredicto = notablemente al día
  (turn_detection="vad", CLAUDE_PLUGINS, _PROC_TIMEOUT=60, puertos, dispatch auto, console/clásico solo como
  historia — todo coincide). Único drift real: `docs/tech-debt-plan.md` listaba D4 (`is_goodbye`) y D5
  (`import os` duplicado) como deuda abierta, pero el código ya las resolvió (U7). FIJADO: ambas marcadas
  ✅ Resuelta en tabla + plan.
- **aidlc-docs/reverse-engineering**: RE refresh cerrado (ver arriba).
- Nota no-drift (no tocada): tabla de latencia en turn-flow.md es snapshot histórico Ciclo 4 (auto-consistente);
  `pyproject.toml` aún declara `livekit-plugins-turn-detector` sin uso post-U10 (deuda de deps, no de docs).
