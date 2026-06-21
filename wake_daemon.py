#!/usr/bin/env python3
"""Wake-word daemon: escucha el mic en continuo con Vosk (local, offline) y dispara
el flujo de saga al oir "claude". Al disparar: beep (= "tu turno, grabando")
y corre UN turno (saga.py en modo wake, estilo Alexa): graba un comando con
auto-stop por silencio, Claude responde, y vuelve a escuchar "claude". No multi-turno.

El mic está abierto SIEMPRE mientras corre este daemon (necesario para el wake word),
pero todo el reconocimiento es local: nada sale a la red hasta que invocás a Claude.

Correr:  .venv/bin/python wake_daemon.py
Parar:   por pid (ps -eo pid,args | awk '/[w]ake_daemon/{print $1}' | xargs kill)
"""

import sys
import os
import json
import queue
import time
import signal
import subprocess
from pathlib import Path

# permitir importar el paquete vc/ sin instalar
sys.path.insert(0, str(Path(__file__).resolve().parent))
from vc.config import (  # noqa: E402
    WAKE_MODEL_DIR, WAKE_GRAMMAR, WAKE_TRIGGER_PHRASES, WAKE_MIN_CONF,
    WAKE_COOLDOWN_S, SAMPLE_RATE, LOG_FILE, PROJECT_DIR,
)
from vc.sound import ensure_beep, play_beep  # noqa: E402

VOICE_CLAUDE = PROJECT_DIR / "saga.py"

import sounddevice as sd  # noqa: E402
from vosk import Model, KaldiRecognizer, SetLogLevel  # noqa: E402

SetLogLevel(-1)  # silenciar el ruido de Kaldi en stderr


def log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] wake: {msg}\n"
    sys.stderr.write(line)
    try:
        with LOG_FILE.open("a") as f:
            f.write(line)
    except OSError:
        pass


def _wake_match(result: dict):
    """Sobre un resultado FINAL de Vosk (SetWords(True): 'text' + 'result' = palabras con
    'conf'), devuelve (text, conf, exact) si el texto contiene la raíz 'claud', o None.
      - text: texto final completo, normalizado.
      - conf: confianza mínima entre las palabras (la más floja manda).
      - exact: True solo si el texto COMPLETO es una WAKE_TRIGGER_PHRASES.
    NO aplica gate ni decide acá: el caller loguea TODO (incluso descartes) para tunear."""
    text = (result.get("text") or "").strip().lower()
    if "claud" not in text:
        return None
    words = result.get("result") or []
    conf = min((float(w.get("conf", 0.0)) for w in words), default=1.0)
    return text, conf, text in WAKE_TRIGGER_PHRASES


def _run_flow(wake_word: str) -> None:
    """Lanza saga en modo wake: UN turno con auto-stop por silencio (sin Win+Z
    para cortar). BLOQUEA hasta que termina: así el mic queda libre para saga y
    el daemon no re-escucha mientras corre. `wake_word` = la palabra que disparó el beep;
    se pasa por env para que el monitor (consola del log) muestre con qué arrancó."""
    env = dict(os.environ, VOICE_WAKE_AUTOSTOP="1", VOICE_WAKE_WORD=wake_word)
    try:
        subprocess.run([sys.executable, str(VOICE_CLAUDE)], env=env, check=False)
    except OSError as e:
        log(f"no pude lanzar el flujo: {e}")


def main() -> int:
    if not WAKE_MODEL_DIR.is_dir():
        log(f"FALTA el modelo Vosk en {WAKE_MODEL_DIR}")
        return 1

    ensure_beep()

    def _bye(_s, _f):
        log("señal de cierre, saliendo")
        sys.exit(0)
    signal.signal(signal.SIGTERM, _bye)
    signal.signal(signal.SIGINT, _bye)

    log(f"cargando modelo Vosk {WAKE_MODEL_DIR.name} ...")
    model = Model(str(WAKE_MODEL_DIR))
    grammar = json.dumps(list(WAKE_GRAMMAR))
    log("modelo listo. escuchando (decí 'claude') ...")

    # Loop maestro: escuchar hasta wake (con el mic abierto) -> SOLTAR el mic ->
    # correr el flujo (que abre su propio mic con auto-stop) -> reanudar escucha.
    # Soltar el mic entre medio evita contención y que el wake oiga el comando/TTS.
    while True:
        word = _listen_until_wake(model, grammar)   # bloquea; beepea y devuelve la palabra
        log(f"wake por '{word}' -> un turno (auto-stop por silencio, modo Alexa) ...")
        _run_flow(word)
        log("turno terminado. reanudando escucha de 'claude' ...")

    return 0


def _listen_until_wake(model, grammar: str) -> str:
    """Abre el mic, escucha en continuo y VUELVE (cerrando el stream) en cuanto oye
    'claude' — tras beepear. Devuelve la frase exacta que matcheó.
    El stream se cierra al salir del `with` -> mic libre.

    SOLO dispara en resultados FINALES de Vosk (NO partials): los partials con grammar
    chica parpadean a cualquier palabra del vocabulario desde ruido / audio del sistema /
    voz lejana -> eran la causa #1 de falsos positivos. Los finales son estables y traen
    confianza por palabra. Además: match de frase EXACTA + gate de confianza + cooldown."""
    rec = KaldiRecognizer(model, SAMPLE_RATE, grammar)
    rec.SetWords(True)  # necesario para la confianza por palabra
    q: "queue.Queue[bytes]" = queue.Queue()

    def cb(indata, _frames, _t, status):
        if status:
            log(f"audio status: {status}")
        q.put(bytes(indata))

    last_fire = 0.0
    with sd.RawInputStream(
        samplerate=SAMPLE_RATE, blocksize=4000, dtype="int16",  # 0.25s/bloque: Vosk cierra el final más rápido -> menos lag de wake
        channels=1, callback=cb,
    ):
        while True:
            data = q.get()
            if not rec.AcceptWaveform(data):
                continue  # partial -> ignorar, esperar al final estable
            result = json.loads(rec.Result())
            m = _wake_match(result)
            if m is None:
                continue
            text, conf, exact = m
            log(f"final candidato '{text}' conf={conf:.2f} exact={exact} (gate={WAKE_MIN_CONF})")
            if not exact:
                continue  # 'claudia'/'claudio'/'claude algo'/embebido -> NO dispara
            if conf < WAKE_MIN_CONF:
                continue  # frase exacta pero confianza floja -> descartar
            if time.time() - last_fire < WAKE_COOLDOWN_S:
                log(f"WAKE ignorado por cooldown '{text}'")
                continue
            last_fire = time.time()
            log(f"WAKE '{text}' (conf={conf:.2f})")
            play_beep()
            return text


if __name__ == "__main__":
    sys.exit(main())
