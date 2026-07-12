# Wake word "hey saga" — Research + Plan (ciclo 2)

> Research verificado (Exa/web, 2026-06). Fuente de la decisión de engine + arquitectura.

## Criterio (corregido): potente, oficial, de calidad, corre DONDE SEA
NO optimizar para edge/Pi por ahora. Elegir lo mejor open-source **oficial** (mantenido por la org),
potente y de calidad, que corra donde se meta la IA (CPU ok, GPU opcional). El wake word es el
trigger primario donde no hay teclado, y debe reconocer **solo la voz de Renzo** (seguridad: la caja
tendrá SSH a la PC main + god-mode + Tailscale; que cualquiera la dispare por voz = agujero).

## Arquitectura objetivo: pipeline LOCAL de 2 etapas

Todo corre local en el host (Pi/mini-PC); nada sale a la nube hasta que el turno está verificado.

```
mic always-on
  └─[1] WAKE WORD (livekit-wakeword, ONNX, ~0.08 FPPH)  → ¿se dijo "hey saga"?
        └─[2] SPEAKER VERIFICATION (ECAPA-TDNN/Resemblyzer)  → ¿es la voz de Renzo? (cosine ≥ umbral)
              └─ dispara el flujo existente (press) → agente LiveKit → Deepgram → Claude → TTS
```

- **Etapa 1 (wake)**: speaker-INdependiente, robusta, barata. Filtra "¿se dijo la frase?".
- **Etapa 2 (speaker)**: biométrica, gate de acceso. Filtra "¿quién la dijo?".
- NO conflar las dos: el wake queda genérico (robusto), la identidad la decide la etapa 2.

## Engine de wake: livekit-wakeword (recomendado)
- Apache-2.0, conv-attention, ~100× menos falsos+ que openWakeWord, 86% recall.
- Corre en single-board computers (Pi ✓). Entrena en un comando, exporta ONNX.
- **Nativo a LiveKit** (saga ya es un agente LiveKit) → ejemplo `hello-wakeword` dispara el agente.
- Backward-compatible con openWakeWord → escape hatch si falla.
- Caveat ES: multilingüe menos preciso que inglés; mitigar con más prompts/samples o fine-tune.
- Alternativa de respaldo: **openWakeWord** (mismo pipeline ONNX, más maduro, peores números).

## Engine de speaker verification: oficiales SOTA (open, Apache-2.0)
Verificado (fuentes oficiales + bench MDPI 2024). EER VoxCeleb1, menor = mejor:
- **SpeechBrain ECAPA-TDNN** (oficial SpeechBrain, Apache-2.0) — EER 0.69%, ~69ms, pretrained HF,
  API trivial (`verify_files`), pure PyTorch. **DEFAULT recomendado**: fácil + top + liviano.
- **3D-Speaker ERes2NetV2 / CAM++** (oficial Alibaba DAMO/ModelScope, Apache-2.0) — EER 0.61%, robusto
  a **multi-device/distance/dialect** (= acento rioplatense + micros distintos). Upgrade por robustez.
- **NVIDIA NeMo TitaNet-Large** (oficial NVIDIA, Apache-2.0) — EER 0.66%, 23M params, SOTA, pero toolkit
  pesado (GPU-leaning). Upgrade por potencia/marca.
- pyannote.audio (oficial, MIT): excelente para diarización, SV puro más flojo (~3.8%); envuelve a los de arriba.
- Descartados: Resemblyzer (community, no oficial), Picovoice Eagle (cerrado), WavLM-SV (EER ~10.9%).
- Flujo: **enrolamiento** una vez (grabar voz de Renzo → voiceprint local, gitignored) → en cada wake,
  extraer embedding de la frase → cosine vs voiceprint → umbral.
- Honesto: biometría de voz = **filtro fuerte, no infalible**; se combina con `guard.py`, no lo reemplaza.
- Flujo: **enrolamiento** una vez (grabar voz de Renzo → voiceprint guardado local, gitignored) →
  en cada wake, extraer embedding del audio de la frase → cosine vs voiceprint → umbral.
- Honesto: la biometría de voz es un **filtro fuerte, no infalible** (grabación/imitación podría
  pasar; resfrío puede fallar). Se combina con el `guard.py` existente, no lo reemplaza.

## NOTA: "speaker ID" de LiveKit ≠ esto
LiveKit Agents tiene `MultiSpeakerAdapter` (diarización vía Deepgram/Speechmatics) — distingue
hablantes en una charla, pero es **cloud** y **relativo** (speaker 1 vs 2), NO biométrico contra una
huella enrolada. No sirve como gate local de "solo mi voz". Es otra cosa.

## NFR DURO: no nerfear la velocidad (regla de Renzo)
La migración whisper/edge → LiveKit+Deepgram bajó la latencia de ~12s a ~2-3s. **Eso NO se toca.**
- Wake word + speaker verify corren **fuera del response path**: son la puerta de activación (reemplazan
  Win+Z), no el motor. El turno (Deepgram STT → Claude → Deepgram TTS) queda IDÉNTICO.
- Costo añadido: wake = inferencia local ~tiempo real (ONNX diminuto); verify = **one-shot ~70ms** sobre
  la frase, antes de la consigna → imperceptible. Nada va a la nube en la puerta.
- **Implica la elección**: favorecer engines livianos/ONNX (ECAPA ~69ms, 3D-Speaker ONNX). NeMo TitaNet
  (toolkit pesado/GPU-leaning) solo si hay GPU; en CPU puede no estar "a la altura".
- **Verificación obligatoria**: benchmark de latencia en vivo (como en la migración) antes de dar OK.
  Si algo regresa la velocidad/calidad del stack actual → se descarta.

## Plan por fases

### Fase A — Wake word en el host actual (x86, este PC)
1. `pip install livekit-wakeword[train,eval,export]` + `setup`.
2. Entrenar "hey saga" (config YAML; evaluar ES synthetic vs fine-tune con voz de Renzo).
3. Integrar el detector en el agente LiveKit (`WakeWordListener` → dispara el `press` interno).
   Coexiste con Win+Z (toggle/opt-in al principio).
4. Verificar en vivo: FPPH real + recall con tu voz/acento. Tunear umbral.

### Fase B — Speaker verification (gate "solo mi voz")
1. Elegir ECAPA-TDNN (precisión) o Resemblyzer (liviano).
2. Flujo de enrolamiento (comando `saga enroll` o por voz): grabar N muestras → voiceprint local.
3. Insertar la etapa 2 tras el wake: cosine ≥ umbral → seguir; si no → ignorar (sin disparar turno).
4. Tunear umbral (balance falso-rechazo vs falso-acepto).

### Fase C — Port a Pi/mini-PC (cuando exista el hardware)
1. Reusar A+B (ambos corren en ARM; convertir a ONNX/onnxruntime, NEON).
2. Resolver el cerebro: Claude Code en ARM tiene fricción de auth (vault) → mini-PC N100 x86 es más
   sólido que Pi. El wake+speaker andan en cualquiera; el riesgo ARM es el `claude` CLI, no esto.
3. Wake = trigger primario (sin teclado). Validar mic/contención always-on.

## Decisiones pendientes (ver wakeword-requirement-questions.md)
Engine de wake, mic always-on, integración, entrenamiento/acento, frase, scope host/Pi, y
**speaker verification: ¿en este ciclo o en la fase Pi? ¿ECAPA o Resemblyzer?**

## Fuentes
- livekit-wakeword (repo + blog): github.com/livekit/livekit-wakeword
- LiveKit diarización (MultiSpeakerAdapter): github.com/livekit/agents examples
- Speaker verif. en Pi: SpeechBrain ECAPA-TDNN (Midway guide), small-footprint SV embedded (arXiv 2011.01709), Resemblyzer eval
