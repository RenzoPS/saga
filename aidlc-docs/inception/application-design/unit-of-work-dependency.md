# Unit of Work — Dependencias y orden — Ciclo 4

## Matriz de dependencias
| Unidad | Depende de | Razón |
|--------|-----------|-------|
| U1 infra (server+token) | — | base de todo |
| U2 worker (modo room) | U1 | necesita el server para registrarse |
| U3 cliente audio | U1 | necesita server + token para unirse |
| U4 wake **server** | U3 (track del mic) | el worker corre el wake sobre el track |
| U5 orbe sync | U3 | usa el track TTS recibido |
| U6 saga-ctl | U1, U2, U3 | orquesta los procesos |

## Orden de implementación sugerido
```
1. U1 (infra room)              ← base: server + tokens. Sin esto nada conecta.
       │
       ├──> 2. U2 (worker room)     ┐ pueden ir en paralelo una vez U1 está
       └──> 3. U3 (cliente audio)   ┘ (worker y cliente son las dos puntas del room)
                    │
                    ├──> 4. U4 (wake server)    ┐ U4=worker sobre el track, U5=cliente; ambas usan U3
                    └──> 5. U5 (orbe sync)      ┘
                                  │
                          6. U6 (saga-ctl)      ← integra y orquesta todo al final
```

## Hito de validación (Build & Test futuro)
- Tras U1+U2+U3: turno básico por room anda (hablás → responde), SIN backlog (el fix del Ciclo 3).
  **Benchmark de latencia acá** (NFR gate: ≤ ~2-3s).
- Tras U4: wake "hey saga" dispara desde el WORKER (sobre el track del mic).
- Tras U5: orbe sincronizado con la voz.
- Tras U6: `saga-ctl start` levanta todo; console sigue como fallback.

## Nota
Cada unidad es chica/acotada; el riesgo mayor está en U3 (cliente de audio nuevo) y U4 (wake sobre el track: dos consumidores + chunking).
El cerebro IA (U2 conserva STT/LLM/TTS/VAD) es bajo riesgo: solo cambia de dónde llega el audio.
