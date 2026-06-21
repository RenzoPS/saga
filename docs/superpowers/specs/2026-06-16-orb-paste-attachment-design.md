# Adjuntar contenido pegado (texto/imagen/link) al turno de voz

**Fecha:** 2026-06-16
**Estado:** diseño aprobado, pendiente implementación

## Problema

Hoy el único input al asistente es la voz (Win+Z → STT → Claude → TTS). No hay forma de
darle material pegado (un texto largo, un deck, una imagen, un link) como contexto de un
turno. Se quiere poder **pegar/escribir contenido y después hablar la consigna** ("analizá
esto", "qué pensás", "calculá lo de la imagen"), recibiendo la respuesta **por voz**.

El contenido pegado **no es el prompt**: es **material adjunto** a un turno de voz normal.
La voz sigue siendo la consigna.

## Restricciones (innegociables)

- **Una sola hotkey**: Win+Z queda idéntico. No se agrega ningún atajo nuevo.
- **No reemplazar nada**: LiveKit (dueño del audio), Deepgram STT/TTS, `claude_daemon`,
  el socket de control y el flujo de 3 fases de Win+Z quedan **intactos**. Es una feature
  aditiva.
- **Reusar lo que ya hay**: el transporte multimodal (one-shot base64 para imágenes) y el
  patrón dead-drop por archivo `/tmp` (ya usado por los screenshots de `grim`).
- **Sin dependencias nuevas**: el clipboard lo lee el navegador (evento `paste`), no Python.

## Arquitectura

### Principio: dead-drop por archivo (mismo patrón que `grim`)

`orb_server` y el agente LiveKit son procesos separados que hoy se comunican en un solo
sentido (agente → `POST /state` → SSE → browser). Para que el contenido pegado llegue al
agente **no se agrega ningún canal nuevo**: se encuentran en archivos `/tmp`.

- El **navegador** captura el paste y lo manda a `orb_server` por HTTP.
- `orb_server` **escribe** el adjunto en `/tmp/saga-attach.{txt,png}`.
- El **agente** lo **lee y borra** en el turno (`lk/claude_llm.py`), exactamente donde hoy
  mete el screenshot de `grim`.

Loose coupling: si el orbe se cae, la voz sigue; si el agente reinicia, el tmp sobrevive.
El POST ocurre en reposo (antes de hablar) → **cero impacto en la latencia de la voz**.

### Flujo completo

1. Llevar el mouse al **borde inferior** de la pestaña del orbe → el panel se abre solo
   (sin clic). El orbe detrás se **difumina + opaca**.
2. Pegar (Ctrl+V) y/o escribir en el panel centrado. Texto → textarea; imagen → chip con
   thumbnail. **Se autoguarda en vivo** (POST a `orb_server` → tmp), sin botón.
3. Cerrar con **Enter / Esc / clic afuera** → el contenido ya quedó cargado; el orbe dispara
   el estado **`attach`** (confirmación) y queda armado. Editable: se puede reabrir y cambiar.
4. **Win+Z** normal → hablar la consigna. Al empezar a grabar (estado `rec`) el panel se
   limpia (el próximo adjunto es nuevo).
5. Al cerrar el turno, el agente lee el adjunto, lo manda **junto con la voz transcripta**
   a Claude, y borra los tmp. Respuesta por voz.

### Reglas de adjunto

- **Texto: overwrite** — el textarea es la fuente de verdad; el browser autoguarda el
  contenido completo en cada cambio (debounce ~350ms). Body vacío → el server borra el tmp.
- **Imagen: la última pisa** (el daemon manda 1 imagen por turno, igual que hoy con
  screenshots). Si hay imagen pegada, tiene **prioridad** sobre el screenshot de "mirá
  pantalla".
- **Texto solo** → va por el `claude_daemon` caliente (mantiene contexto multivuelta).
- **Imagen** → va por el one-shot base64 (frío, sin contexto) — limitación que ya existe
  hoy con los screenshots, no se introduce acá.
- **Consume-once**: el adjunto se borra apenas se consume en un turno.

## Componentes (superficie mínima)

| Archivo | Cambio |
|---|---|
| `vc/config.py` | Constantes `ATTACH_TEXT_PATH = /tmp/saga-attach.txt` y `ATTACH_IMG_PATH = /tmp/saga-attach.png` (al lado de `SCREENSHOT_PATH`). |
| `vc/attach.py` *(nuevo, ~30 líneas)* | `has_staged() -> bool`, `take_staged() -> tuple[str\|None, Path\|None]` (lee ambos tmp, los borra, devuelve contenido). IO puro → testeable con `unittest`. |
| `orb/orb_server.py` | Endpoint `POST /attach?kind=text\|image`: lee el body, **overwrite** del tmp (body vacío → borra), responde 204. Importa las paths de `vc.config` (con `sys.path.insert` del root, igual que los demás daemons del repo). Agrega `attach` a `VALID_STATES`. |
| `orb/orb.html` | (1) Panel **centrado** con backdrop que difumina+opaca el orbe; se abre solo al llevar el mouse al borde inferior; textarea + chip de imagen, **sin botones** (autoguardado). (2) Captura `paste` (texto y/o imagen). (3) Cierre con Enter/Esc/clic afuera. (4) Estado nuevo `attach` en la tabla `PH` (magenta) + `TRANSIENT`. (5) Animación de absorción (`absorbV`, espeja `flashV`). (6) Indicador "armado" sutil. (7) Limpieza de la UI al estado `rec` (`window.__attachTurnStart`). |
| `lk/claude_llm.py` | En `_run`/`_worker`: antes de la lógica de screenshot, `take_staged()`. Si hay texto, se antepone al prompt (`"<adjunto>\n\n<voz>"`). Si hay imagen, se usa como `screenshot_path` (prioridad sobre el visual command). El `shot.unlink()` que ya existe cubre el cleanup de la imagen del adjunto. Guard: si `prompt` vacío y no hay staged → return (no consumir). |

### UI del panel (`orb.html`)

- **Abrir (sin clic)**: al llevar el mouse al borde inferior (`clientY >= innerHeight-3`) el
  panel se abre solo. Un chevron `⌃` tenue al pie brilla cuando el puntero se acerca (~70px).
- **Panel**: backdrop full-screen `rgba(2,4,7,.5)` + `backdrop-filter: blur(16px)` sobre el
  canvas (difumina+opaca el orbe), con un **card centrado** (fade+scale in). Contenido:
  encabezado "Adjunto para el próximo turno", textarea (placeholder "Pegá o escribí lo que
  querés adjuntar… (Ctrl+V también pega imágenes)"), chip de imagen (thumbnail + ✕ quitar),
  y un pie con el hint. **Sin botones**.
- **Paste dentro del panel**: texto → textarea (default); imagen (`clipboardData.items`,
  `type.startsWith('image/')` → `getAsFile()`) → chip con thumbnail + POST inmediato.
- **Autoguardado (sin botón)**: el textarea es la fuente de verdad. En cada `input`
  (debounce ~350ms) POST `/attach?kind=text` con el contenido completo (overwrite; vacío
  borra). La imagen se postea al pegarla; el ✕ postea body vacío para borrarla.
- **Cerrar**: Enter (sin Shift; Shift+Enter = salto de línea), Esc, o clic afuera del card.
  Al cerrar con contenido → `setState('attach')` (`armed=true`). El contenido **persiste y es
  editable** hasta que arranca un turno.
- **Consumo**: al estado `rec` (Win+Z empezó a grabar) el browser limpia textarea + chip
  (`window.__attachTurnStart`); el agente borra los tmp al cerrar el turno.
- **Guard de performance**: el blur solo corre con el panel abierto. Si pesa en GPU, fallback
  a fondo semi-opaco sin blur.

### Estado `attach` del orbe

- **Color**: magenta/fucsia `[1.0, 0.30, 0.80]` — único, no pisa el lila de `screen`
  `[0.73,0.53,0.97]` ni el violeta de `think` `[0.55,0.22,0.92]`.
- **Glyph**: `📎 Cargado`.
- **Animación de absorción**: transiente `absorbV` (set a 1 al entrar, decae, espeja el
  patrón de `flashV`/`wobbleV`). Efecto: la red se **contrae hacia el núcleo en una onda** y
  rebota (el orbe "traga" el contenido) + flash de bloom magenta. Dura ~1.4s vía `TRANSIENT`
  y vuelve a `idle` solo.
- **Indicador "armado"**: mientras `armed && mode==='idle'`, un acento magenta tenue (puntito
  orbitando / rim leve). Browser-local; se limpia cuando llega el próximo estado distinto de
  `idle`/`attach` (arranque del turno). Sin sync con el server.

## Privacidad

El contenido pegado puede tener secretos. Los tmp `attach.{txt,png}` se borran apenas se
consumen en el turno (mismo criterio que los screenshots de `grim`, que ya se borran en el
`finally` de `_worker`). Permisos `0o600` consistentes con el resto del proyecto.

## Verificación

- `py_compile` de los `.py` tocados.
- `unittest` de `vc/attach.py` (escribir tmp → `take_staged()` → assert contenido + que
  borró los archivos; caso vacío → `has_staged()` False).
- Prueba visual del estado `attach` con Playwright: simular evento `paste` + `setState('attach')`,
  screenshot, verificar color/animación y el panel.
- El flujo de audio en vivo (Win+Z) lo prueba el usuario.

## Fuera de scope (YAGNI)

- Sincronizar el indicador "armado" con el server (consumo real del turno). El browser lo
  resuelve localmente; basta.
- Múltiples imágenes por turno (el daemon manda 1).
- Drag&drop de archivos desde el file manager (solo clipboard + tipeo por ahora).
