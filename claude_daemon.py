#!/usr/bin/env python3
"""Daemon de Claude: mantiene UN proceso `claude` (modo stream-json persistente)
vivo entre turnos -> plugins + sesión calientes -> mata el cold-start (~5s) que
se pagaba al spawnear el CLI en cada Win+Z.

voice_claude (efímero) es CLIENTE: manda el turno por socket Unix y recibe los
text_delta. Si este daemon no está, el cliente cae al spawn one-shot de siempre.

Protocolo socket (newline-delimited JSON):
  req:   {"prompt": "...", "image_b64": "<png b64 opcional>"}   |   {"reset": true}
  resp:  {"delta": "..."}\\n ...  ->  {"done": true}\\n   |   {"error": "..."}\\n
"""

import os
import sys
import json
import time
import socket
import signal
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vc.config import (
    CLAUDE_SOCK, CLAUDE_MODEL, CLAUDE_FAST_FLAGS, CLAUDE_SKIP_PERMISSIONS,
    CLAUDE_SYSTEM_PROMPT, CLAUDE_DAEMON_IDLE_S, LOG_FILE,
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
        args = [
            "claude", "-p",
            "--model", CLAUDE_MODEL,
            "--output-format", "stream-json",
            "--input-format", "stream-json",
            "--verbose", "--include-partial-messages",
            "--append-system-prompt", CLAUDE_SYSTEM_PROMPT,
            flag, sid,
        ]
        args += CLAUDE_FAST_FLAGS
        if CLAUDE_SKIP_PERMISSIONS:
            args.append("--dangerously-skip-permissions")
        t0 = time.monotonic()
        self.p = subprocess.Popen(
            args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1,
        )
        self._session_flag = flag
        log(f"claude spawned ({flag} {sid[:8]}…) en {time.monotonic()-t0:.1f}s")

    def alive(self) -> bool:
        return self.p is not None and self.p.poll() is None

    def kill(self) -> None:
        if self.p and self.p.poll() is None:
            try:
                self.p.terminate()
                try:
                    self.p.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.p.kill()
            except Exception:
                pass
        self.p = None

    def reset(self) -> None:
        self.spawn(fresh=True)   # nueva uuid + respawn (conversación limpia)

    def turn(self, prompt: str, image_b64: "str | None", send_delta) -> bool:
        """Manda un turno y reenvía text_deltas. Si la sesión está muerta
        (--resume a una uuid que ya no existe) o claude murió, respawnea con
        sesión fresca y reintenta UNA vez. Devuelve True si terminó OK."""
        for attempt in (1, 2):
            if not self.alive():
                self.spawn(fresh=(attempt == 2))
            res = self._one_turn(prompt, image_b64, send_delta)
            if res == "ok":
                return True
            if attempt == 1 and res in ("session_error", "dead"):
                log(f"turno falló ({res}) -> respawn sesión fresca + reintento")
                self.spawn(fresh=True)
                continue
            return False
        return False

    def _one_turn(self, prompt: str, image_b64: "str | None", send_delta) -> str:
        """Un intento. Devuelve 'ok' | 'session_error' (result is_error) | 'dead'."""
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

        client_gone = False
        while True:
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
                if ev.get("type") == "content_block_delta":
                    d = ev.get("delta", {})
                    if d.get("type") == "text_delta":
                        txt = d.get("text", "")
                        if txt and not client_gone:
                            if not send_delta(txt):   # cliente se fue (cancel)
                                client_gone = True     # drenamos hasta 'result'
            elif typ == "result":
                if o.get("is_error"):              # ej: "No conversation found" -> sesión muerta
                    return "session_error"
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

                    def send_delta(txt: str) -> bool:
                        try:
                            conn.sendall((json.dumps({"delta": txt}) + "\n").encode())
                            return True
                        except OSError:
                            return False

                    ok = claude.turn(req.get("prompt", ""), req.get("image_b64"), send_delta)
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
