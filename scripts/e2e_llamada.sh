#!/usr/bin/env bash
# E2E del modo llamada, SIN micrófono humano.
#
# Lanza un cliente Chromium headless con micrófono FALSO alimentado por un .wav, abre la
# línea por el socket de control y mira qué queda en saga.log. Es la única forma de validar
# el loop completo (voz -> STT -> Claude -> TTS -> voz) sin que haya alguien hablándole.
#
#   scripts/e2e_llamada.sh <archivo.wav> [segundos_de_espera]
#
# El .wav tiene que ser PCM 16-bit (Chrome no acepta otra cosa como fake capture).
#
# `%noloop` NO es decorativo: sin eso Chrome repite el archivo en loop infinito, el usuario
# falso "no deja de hablar" nunca, y Flux jamás cierra el turno. Se ve como audio entrando y
# cero transcript, que parece un bug del STT y no lo es.
set -o nounset -o pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WAV="${1:?uso: e2e_llamada.sh <archivo.wav> [segundos]}"
ESPERA="${2:-45}"
CHROME="$HOME/.cache/ms-playwright/chromium-1237/chrome-linux64/chrome"
PERFIL="$(mktemp -d)"
LOG="$ROOT/saga.log"

[ -x "$CHROME" ] || { echo "no encuentro chromium en $CHROME"; exit 1; }
[ -f "$WAV" ]    || { echo "no encuentro el wav: $WAV"; exit 1; }

cd "$ROOT"
URL="$(.venv/bin/python -c 'from vc.config import orb_token; print("http://127.0.0.1:8777/?token="+orb_token())' 2>/dev/null | tail -1)"

MARCA=$(wc -l < "$LOG")           # desde acá leemos: todo lo anterior es ruido viejo

echo "▸ cliente headless con mic falso: $(basename "$WAV")"
"$CHROME" --headless=new --enable-unsafe-swiftshader \
  --use-fake-ui-for-media-stream --use-fake-device-for-media-stream \
  --use-file-for-fake-audio-capture="$WAV%noloop" \
  --autoplay-policy=no-user-gesture-required \
  --no-first-run --no-default-browser-check \
  --user-data-dir="$PERFIL" "$URL" > "$PERFIL/chrome.log" 2>&1 &
CHROME_PID=$!
# shellcheck disable=SC2064
trap "kill $CHROME_PID 2>/dev/null; rm -rf '$PERFIL'" EXIT

echo "▸ esperando que el agente entre al room…"
for _ in $(seq 1 30); do
  [ -S /tmp/saga-lk-ctl.sock ] && break
  sleep 1
done
[ -S /tmp/saga-lk-ctl.sock ] || { echo "✗ el agente no entró al room"; exit 1; }
echo "  ✓ agente adentro"

echo "▸ Win+Z: abro la línea"
.venv/bin/python -c "
import socket
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(5)
s.connect('/tmp/saga-lk-ctl.sock'); s.sendall(b'press\n'); s.close()
" || { echo "✗ no pude mandar press"; exit 1; }

echo "▸ escuchando ${ESPERA}s…"
sleep "$ESPERA"

echo
echo "──────── saga.log del turno ────────"
tail -n +$((MARCA + 1)) "$LOG" | grep -vE "STTMetrics  duration=0.000s  audio_duration=0.000s"
