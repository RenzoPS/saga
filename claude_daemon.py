#!/usr/bin/env python3
"""Daemon de Claude: mantiene UN proceso `claude` (modo stream-json persistente)
vivo entre turnos -> plugins + sesión calientes -> mata el cold-start (~5s) que
se pagaba al spawnear el CLI en cada Win+Z.

saga (efímero) es CLIENTE: manda el turno por socket Unix y recibe los
text_delta. Si este daemon no está, el cliente cae al spawn one-shot de siempre.

Protocolo socket (newline-delimited JSON):
  req:   {"prompt": "...", "image_b64": "<png b64 opcional>"}   |   {"reset": true}
  resp:  {"delta": "..."}   texto hablable
         {"tool": "Bash"}   Claude arrancó una tool (para el orbe/log)
         {"break": true}    fin de BLOQUE: Claude deja de hablar y se va a laburar
         -> {"done": true}  |  {"error": "..."}

El `break` es la pieza clave del turno segmentado: un turno de Claude Code NO es un
stream continuo (texto -> hueco de tools de 100s+ -> texto). Sin cortar en el hueco, el
websocket del TTS queda abierto esperando y Deepgram lo mata por inactividad
(APITimeoutError) -> la respuesta final llega a un canal muerto y NO SE ESCUCHA.
"""

import os
import sys
import json
import time
import socket
import select
import signal
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vc.config import (
    CLAUDE_SOCK, CLAUDE_DAEMON_IDLE_S, CLAUDE_DAEMON_TURN_TIMEOUT_S, LOG_FILE,
    build_claude_base_args, PLUGINS_MODE, DISABLED_PLUGINS,
)
from vc.session import get_active_session_id, reset_session

SOCK_PATH = CLAUDE_SOCK


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] claude-daemon: {msg}\n"
    sys.stderr.write(line)
    try:
        with LOG_FILE.open("a") as f:
            f.write(line)
    except OSError:
        pass


class ClaudeProc:
    """El proceso `claude` persistente. Lo respawnea si muere o al resetear sesión."""

    def __init__(self) -> None:
        self.p: "subprocess.Popen | None" = None
        self.spawn()

    def spawn(self, fresh: bool = False) -> None:
        self.kill()
        if fresh:
            sid = reset_session()      # uuid nueva -> --session-id (conversación limpia)
            flag = "--session-id"
        else:
            sid, is_new = get_active_session_id()
            flag = "--session-id" if is_new else "--resume"
        # fuente única de args (compartida con el one-shot) + modo persistente stdin
        args = build_claude_base_args(sid, flag) + ["-p", "--input-format", "stream-json"]
        t0 = time.monotonic()
        self.p = subprocess.Popen(
            args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1,
            start_new_session=True,   # grupo propio -> al matar, matamos TODO el árbol (subspawns de claude-mem incluidos)
        )
        self._session_flag = flag
        _off = f", off={','.join(p.split('@')[0] for p in DISABLED_PLUGINS)}" if DISABLED_PLUGINS else ""
        log(f"claude spawned ({flag} {sid[:8]}…, plugins={PLUGINS_MODE}{_off}) en {time.monotonic()-t0:.1f}s")

    def alive(self) -> bool:
        return self.p is not None and self.p.poll() is None

    def kill(self) -> None:
        if self.p and self.p.poll() is None:
            try:
                pgid = os.getpgid(self.p.pid)
                os.killpg(pgid, signal.SIGTERM)   # mata el grupo entero (claude + subspawns de claude-mem)
                try:
                    self.p.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                try:
                    self.p.kill()
                except Exception:
                    pass
        self.p = None

    def reset(self) -> None:
        self.spawn(fresh=True)   # nueva uuid + respawn (conversación limpia)

    def turn(self, prompt: str, image_b64: "str | None", send) -> bool:
        """Manda un turno y reenvía los eventos (texto/tool/break). Si la sesión está
        muerta (--resume a una uuid que ya no existe) o claude murió, respawnea con
        sesión fresca y reintenta UNA vez. Devuelve True si terminó OK."""
        for attempt in (1, 2):
            if not self.alive():
                self.spawn(fresh=(attempt == 2))
            res = self._one_turn(prompt, image_b64, send)
            if res == "ok":
                return True
            if res == "cancelled":
                return True   # cancelado por el cliente: turno MANEJADO, NO reintentar el prompt
            if res == "turn_error":
                # La sesión VIVE (num_turns>0): el turno falló por otra cosa. Reintentar el mismo
                # prompt duplicaría lo que Claude ya hizo (tools incluidas), y respawnear fresco
                # tiraría la conversación. Se falla este turno y punto: el contexto queda intacto.
                log("turno falló pero la sesión sigue viva -> NO la reseteo (contexto intacto)")
                return False
            if attempt == 1 and res in ("session_error", "dead"):
                log(f"turno falló ({res}) -> respawn sesión fresca + reintento")
                self.spawn(fresh=True)
                continue
            return False
        return False

    def _one_turn(self, prompt: str, image_b64: "str | None", send) -> str:
        """Un intento. Devuelve:
          'ok'            -> drenado completo, sesión consistente
          'turn_error'    -> el turno falló pero la sesión VIVE (num_turns>0): no resetear
          'session_error' -> la sesión no existe (num_turns=0): respawn fresco
          'cancelled'     -> el cliente cortó
          'dead'          -> el proceso claude no está
        """
        if not self.alive():
            return "dead"
        if image_b64:
            content = [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_b64}},
                {"type": "text", "text": prompt},
            ]
        else:
            content = prompt
        msg = json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n"
        try:
            self.p.stdin.write(msg)
            self.p.stdin.flush()
        except (BrokenPipeError, OSError):
            return "dead"

        deadline = time.monotonic() + CLAUDE_DAEMON_TURN_TIMEOUT_S
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:          # turno colgado -> matar para no trabar el daemon
                log(f"turno excedió {CLAUDE_DAEMON_TURN_TIMEOUT_S:.0f}s -> mato claude (respawn en el próximo)")
                self.kill()
                return "dead"
            ready, _, _ = select.select([self.p.stdout], [], [], min(remaining, 1.0))
            if not ready:               # nada todavía -> re-chequear deadline
                continue
            line = self.p.stdout.readline()
            if not line:               # claude murió / EOF
                return "dead"
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            typ = o.get("type")
            if typ == "stream_event":
                ev = o.get("event", {})
                et = ev.get("type")
                # Nota: los bloques `thinking` emiten `thinking_delta`, NO `text_delta`
                # -> el razonamiento interno nunca llega al TTS. Solo va lo hablable.
                if et == "content_block_delta":
                    d = ev.get("delta", {})
                    if d.get("type") == "text_delta":
                        txt = d.get("text", "")
                        if txt and not send({"delta": txt}):
                            # El cliente CANCELÓ (cerró el socket) -> ABORTAR el turno YA, no drenar:
                            # mato el grupo entero (claude + subspawns de claude-mem) -> daemon libre,
                            # SIN zombie ni huérfanos. El próximo turno respawnea con --resume (el
                            # contexto hasta el último turno COMPLETO se mantiene; el abortado no se guardó).
                            log("cliente canceló -> mato el turno en curso (respawn --resume en el próximo)")
                            self.kill()
                            return "cancelled"
                elif et == "content_block_start":
                    cb = ev.get("content_block", {})
                    if cb.get("type") == "tool_use":
                        send({"tool": cb.get("name") or "?"})   # informativo: no corta nada
                elif et == "message_delta":
                    # stop_reason=tool_use -> Claude terminó de hablar y se va a usar tools.
                    # Ese es el CORTE del bloque: el cliente cierra su segmento de TTS y el hueco
                    # de trabajo transcurre sin ningún websocket abierto (sin APITimeoutError).
                    if ev.get("delta", {}).get("stop_reason") == "tool_use":
                        send({"break": True})
            elif typ == "result":
                if o.get("is_error"):
                    # `is_error` NO significa "la sesión murió". Significa cualquier cosa: tope de
                    # tokens, sobrecarga de la API, una tool que falló, un turno demasiado largo.
                    # Antes todos caían en "session_error" y `turn()` respondía con `spawn(fresh=True)`
                    # -> uuid nueva -> CONVERSACIÓN DESTRUIDA en silencio, a mitad de una llamada.
                    # Visto en vivo: Claude recitó Génesis 1 entero, el turno falló, y el
                    # "¿cómo se llama el capítulo?" siguiente llegó a un Claude recién nacido que
                    # se puso a buscar "biblia" en el repo.
                    #
                    # El discriminador es `num_turns`: una sesión que NO existe nunca llega a correr
                    # (num_turns=0, duration_ms=0). Si el turno corrió, la sesión está VIVA y lo
                    # último que hay que hacer es tirarla.
                    subtype = o.get("subtype", "?")
                    turns = o.get("num_turns", 0)
                    detail = str(o.get("result") or "")[:200]
                    log(f"turno con error: subtype={subtype} num_turns={turns}"
                        + (f" detalle={detail!r}" if detail else ""))
                    if turns == 0:
                        return "session_error"     # la sesión no existe -> respawn fresco
                    return "turn_error"            # la sesión vive: fallo este turno, no la matés
                return "ok"                        # drenado completo -> sesión consistente


def main() -> int:
    # Anti doble-arranque
    if SOCK_PATH.exists():
        try:
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            probe.settimeout(0.5)
            probe.connect(str(SOCK_PATH))
            probe.close()
            log("ya hay daemon vivo, salgo")
            return 0
        except OSError:
            SOCK_PATH.unlink(missing_ok=True)

    claude = ClaudeProc()

    # SIGTERM/SIGINT -> salir limpio (el finally mata el claude hijo, no queda huérfano)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))

    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(SOCK_PATH))
    os.chmod(SOCK_PATH, 0o600)   # solo el dueño puede conectar (sin esto = RCE local con god-mode)
    srv.listen(4)
    srv.settimeout(CLAUDE_DAEMON_IDLE_S)
    log(f"escuchando en {SOCK_PATH} (idle {CLAUDE_DAEMON_IDLE_S:.0f}s)")

    try:
        while True:
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                log("idle timeout, apago")
                return 0
            with conn:
                try:
                    conn.settimeout(180)
                    buf = b""
                    while b"\n" not in buf:
                        chunk = conn.recv(4096)
                        if not chunk:
                            break
                        buf += chunk
                    if not buf:
                        continue
                    req = json.loads(buf.split(b"\n", 1)[0].decode())

                    if req.get("reset"):
                        claude.reset()
                        conn.sendall(b'{"done": true}\n')
                        continue

                    def send(obj: dict) -> bool:
                        try:
                            conn.sendall((json.dumps(obj) + "\n").encode())
                            return True
                        except OSError:
                            return False

                    ok = claude.turn(req.get("prompt", ""), req.get("image_b64"), send)
                    if ok:
                        try:
                            conn.sendall(b'{"done": true}\n')
                        except OSError:
                            pass
                    else:
                        log("claude murió en el turno -> respawn para el próximo")
                        claude.spawn()   # dejarlo listo para la próxima
                        try:
                            conn.sendall(b'{"error": "claude died"}\n')
                        except OSError:
                            pass
                except Exception as e:
                    log(f"req error: {type(e).__name__}: {e}")
                    try:
                        conn.sendall((json.dumps({"error": str(e)}) + "\n").encode())
                    except OSError:
                        pass
    finally:
        claude.kill()
        SOCK_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
