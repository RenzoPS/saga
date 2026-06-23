#!/usr/bin/env python3
"""Entrena el modelo wake word 'hey saga' usando TTS sintético en español.

Uso:
    # 1. Instalar deps de entrenamiento (solo para training, no runtime):
    .venv/bin/pip install 'livekit-wakeword[train,eval,export,voxcpm]'

    # 2. Sistema (Arch Linux):
    sudo pacman -S portaudio

    # 3. Entrenar:
    .venv/bin/python scripts/train_wakeword.py

Salida: models/hey_saga/hey_saga.onnx
Activar: SAGA_WAKE_ENABLED=1 SAGA_WAKE_MODEL=models/hey_saga/hey_saga.onnx \\
         .venv/bin/python lk/agent.py console
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from livekit.wakeword import (
    WakeWordConfig,
    run_generate,
    run_augment,
    run_extraction,
    run_train,
    run_export,
    run_eval,
)

_OUTPUT_DIR = os.path.join(_ROOT, "models")
os.makedirs(_OUTPUT_DIR, exist_ok=True)

config = WakeWordConfig(
    model_name="hey_saga",
    target_phrases=["hey saga"],
    n_samples=5000,
    n_samples_val=1000,
    tts_backend="piper_vits",   # positivos rápidos (~1.3s/clip vs 51s VoxCPM en CPU). El fix real es ACAV (negativos reales), no el TTS.
    output_dir=_OUTPUT_DIR,
    data_dir=os.path.join(_ROOT, "models", "_data"),
)

print("=== [1/5] Generando samples sintéticos (piper TTS, ~1.3s/clip en CPU) ===")
run_generate(config)

print("\n=== [2/5] Augmentación (ruido, reverb, pitch) ===")
run_augment(config)

print("\n=== [3/5] Extracción de features (mel + speech embeddings) ===")
run_extraction(config)

print("\n=== [4/5] Entrenamiento ===")
run_train(config)

print("\n=== [5/5] Exportando a ONNX ===")
onnx_path = run_export(config)
print(f"    Modelo: {onnx_path}")

print("\n=== Evaluación ===")
results = run_eval(config, onnx_path)
print(f"    AUT={results['aut']:.4f}  FPPH={results['fpph']:.2f}  Recall={results['recall']:.1%}")
print()
print("Listo. Para activar wake word:")
print(f"  export SAGA_WAKE_ENABLED=1")
print(f"  export SAGA_WAKE_MODEL={onnx_path}")
print(f"  .venv/bin/python lk/agent.py console")
