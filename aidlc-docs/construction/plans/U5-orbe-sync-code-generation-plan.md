# U5 — Orbe sincronizado con la voz real · Code Generation Plan (Ciclo 4)

> Fuente única de verdad para Code Generation de U5. El orbe late con el nivel REAL de la voz de saga
> (track TTS), reemplazando la animación sintética. Lo DESBLOQUEÓ el modo room: el browser recibe el track
> TTS directo (en console el audio vivía en otro proceso → sync imposible, ver backlog del proyecto).
> Depende de U3 (el cliente recibe el track TTS).

> NOTA AI-DLC: este plan se escribió DURANTE el Build&Test (post-implementación) porque U5 se encaró en una
> iteración rápida de pulido en vivo. Se formaliza acá para mantener la trazabilidad del framework.

## Stages condicionales (Per-Unit Loop)
- Functional/NFR/Infra Design — SKIP (cambio de animación frontend; sin modelos/lógica/infra nueva).
- Code Generation — EXECUTE.

## Decisiones técnicas
1. **Medición**: `AnalyserNode` de Web Audio sobre `track.mediaStreamTrack` del TTS (modo time-domain →
   RMS = volumen). NO se conecta a `destination` (el `<audio>` ya reproduce; el analyser SOLO mide).
2. **Nivel expuesto**: `window.__ttsLevel()` → RMS 0..1 de la voz en vivo (escalado ×2.2; la voz tiene RMS bajo).
3. **Uso en el orbe**: en estado `speak`, `lvl` = nivel real suavizado; el resto de los estados siguen
   sintéticos. Fallback: si el analyser falla/da 0 → queda el sintético (nunca queda plano). try/catch en el
   frame para no romper el render.
4. **Suavizado de ENVOLVENTE**: ataque rápido (0.18) / release lento (0.08) + `smoothingTimeConstant=0.85`
   en el analyser → la red sigue la envolvente de la voz, no parpadea por sílaba.
5. **Techo de escala** (0.38): pulsa con la voz pero NO se infla de más.
6. **Autoplay**: el AudioContext arranca suspended → se resume en el primer gesto (click/tecla). El `<audio>`
   se desbloquea con `room.startAudio()` también en el primer gesto — SIN botón (se sacó el "tocá para activar audio").

## Archivos afectados
| Archivo | Acción | Detalle |
|---|---|---|
| `orb/orb.html` | MOD | `_setupTTSAnalyser`, `window.__ttsLevel`, uso en el frame, suavizado+techo, unlock por gesto |

## Riesgos / mitigación
- **Autoplay bloqueado** → resume del AudioContext + `startAudio()` en el primer gesto.
- **Analyser falla / no hay audio** → fallback sintético + try/catch → el orbe nunca queda inmóvil.
- **Jitter visual** → suavizado de envolvente + techo de escala.

---

# PART 1 — PLANNING (este documento)
- [x] Step 1-5: contexto (orb.html: audioLevel/frame, hook ya existente `voice=1+lvl*0.14*wSpeak`), plan, resumen
- [x] Step 6-9: (retroactivo — se documenta post-Build&Test) Part 1 OK

# PART 2 — GENERATION
- [x] **Step 10**: `_setupTTSAnalyser(track)` — AnalyserNode sobre el track TTS (solo mide)
- [x] **Step 11**: `window.__ttsLevel()` — RMS 0..1, escala ×2.2
- [x] **Step 12**: frame del orbe — usa nivel real en `speak`, suavizado envolvente + techo 0.38, fallback sintético
- [x] **Step 13**: autoplay — resume AudioContext + startAudio en el primer gesto; botón eliminado
- [x] **Step 14**: Verificación — en vivo en el browser real del usuario (no headless: WebRTC). Resultado: 10/10.
- [x] **Step 15**: Summary (construction/U5-orbe-sync/code/) + aidlc-state.md

## Criterio de "U5 hecho"
- El orbe late con la voz real de saga al hablar; suave (no parpadea), no se infla de más.
- Nunca queda inmóvil (fallback sintético). Audio se desbloquea sin botón.
- Verificado EN VIVO por el usuario (10/10). Commit: `ed7620c`.
