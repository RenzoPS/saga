# U10 — RAM del turn detector · Requirements Questions

Contexto: el turn detector semántico (`MultilingualModel`, EOU) ocupa **~1.8 GB RAM** (el 67% de la RAM
del worker). Decide el fin de turno por el _sentido_ de la frase (anti-chopping). Reemplazarlo libera esa
RAM pero cambia cómo se cierra el turno.

Respondé cada pregunta poniendo tu opción después del tag `[Answer]:`. Si elegís "Other", describilo ahí.

---

## Question 1

¿Qué tan prioritario es bajar la RAM **ahora**? (define si vale pagar el trade-off de calidad de turno)

A) Alta — apunto a Raspberry / mini-PC pronto, la RAM es el cuello

B) Media — sigo en la PC (30 GB), no urge, pero quiero dejarlo listo/optimizado igual

C) Baja — es solo curiosidad; si el trade-off molesta, mejor no tocarlo

X) Other (describir después de [Answer]:)

[Answer]: C, pero estaria bueno chequearlo

---

## Question 2

El cambio implica cerrar el turno por **silencio** (VAD) en vez de por **sentido** (semántico). En la
práctica: si hacés pausas largas a mitad de frase, el VAD puede cortarte y mandar incompleto. ¿Lo aceptás?

A) Sí — hablo en frases directas + uso Win+Z igual; el corte por silencio me sirve

B) Solo si la degradación es mínima — quiero probar en vivo antes de comprometerme

C) No quiero perder el cierre semántico — buscá otra forma de ahorrar RAM (o no lo toques)

X) Other (describir después de [Answer]:)

[Answer]: B, pero creo q con 3 segundos de tiempo, en el que NO SE DETECTA VOZ (ENTIENDO QUE SE USA SILERO), alcanza y sobra.

---

## Question 3

Hay una opción intermedia: cerrar el turno por el **endpointing del STT de Deepgram** (Deepgram ya manda
eventos de fin de habla). No carga el transformer (ahorra la RAM) y es más "inteligente" que VAD puro, pero
es más trabajo y hay que verificar soporte en livekit-agents 1.6. ¿La exploro?

A) Sí — preferiría STT endpointing si funciona; VAD puro como fallback

B) No — andá directo a VAD puro (simple, máximo ahorro, ya está cargado)

C) Decidí vos en Functional Design según qué sea más limpio/confiable

X) Other (describir después de [Answer]:)

[Answer]: B, ENTIENDO QUE SILERO YA ESTA HOY ACTIVO, osea, TENEMOS TANTO silencio, como SENTIDO (y para ser franco, generalmente se corta por silencio)

---

## Question 4

Alcance de U10: ¿solo el turn detector, o aprovecho para mirar otros consumos de RAM del worker?

A) Solo el turn detector (foco, unidad chica como U9)

B) Turn detector + un relevamiento rápido de qué más pesa (sin comprometerme a tocarlo)

X) Other (describir después de [Answer]:)

[Answer]: B
