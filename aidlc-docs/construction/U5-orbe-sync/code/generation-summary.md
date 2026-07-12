# U5 — Orbe sincronizado con la voz real · Generation Summary (Ciclo 4)

> El orbe late con el nivel REAL del track TTS (Web Audio), reemplazando la animación sintética.
> Desbloqueado por el modo room. Commit: `ed7620c`.

## Archivo modificado
- **`orb/orb.html`**:
  - `_setupTTSAnalyser(track)` — crea un `AudioContext` + `MediaStreamSource` desde `track.mediaStreamTrack` +
    `AnalyserNode` (`fftSize=256`, `smoothingTimeConstant=0.85`). `src.connect(analyser)` SOLO mide (no a
    `destination`: el `<audio>` ya reproduce). Resume del AudioContext en el primer gesto (suspended por autoplay).
  - `window.__ttsLevel()` — `getByteTimeDomainData` → RMS 0..1 (×2.2, la voz tiene RMS bajo).
  - Frame del orbe: en `mode==='speak'` usa el nivel real suavizado (ataque 0.18 / release 0.08) con TECHO
    0.38 (pulsa pero no se infla); fallback al sintético + try/catch (nunca queda plano).
  - Autoplay: `showUnlock` ya no pone botón — desbloquea `room.startAudio()` + resume del AudioContext en el
    primer click/tecla. Se eliminó el botón "tocá para activar audio".

## Por qué el modo room lo hizo posible
En console el audio de TTS vivía en otro proceso (pacat) → sincronizar con el browser por HTTP siempre tenía
lag (ver backlog "Orbe — sync real" en aidlc-state). En room el browser RECIBE el track TTS directo → Web
Audio AnalyserNode sobre el track = sync perfecto, dentro del mismo runtime.

## Verificación
- EN VIVO en el browser real del usuario (no headless: el WebRTC no levanta en Playwright). El usuario validó:
  el orbe late con la voz, suave (no parpadea), no se infla de más, audio sin botón. **Resultado: 10/10.**

## Iteraciones de pulido (Build&Test)
1. Primera versión: nivel real con piso 0.06 → quedaba plano / no captaba (AudioContext suspended) → robusto
   (fallback sintético + resume por gesto).
2. Parpadeo en habla rápida → suavizado de envolvente (ataque/release asimétrico) + `smoothingTimeConstant 0.85`.
3. Se inflaba de más → techo 0.38 + escala ×2.2.
4. Botón de autoplay molesto → unlock silencioso por gesto.
