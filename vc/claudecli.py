"""Invocación a Claude. Camino rápido: daemon persistente (proceso `claude`
caliente, sin cold-start). Fallback robusto: spawn one-shot `claude -p` (lo de
siempre) si el daemon no está o falla. Maneja sesión e imagen."""

import os
import sys
import base64
import json
import time
import socket
import subprocess
from pathlib import Path
from typing import Callable, Iterator

from .config import (
    CLAUDE_TIMEOUT_S,
    CLAUDE_SOCK,
    CLAUDE_DAEMON,
    build_claude_base_args,
)
from .runtime import log, _cancel
from .session import get_active_session_id, touch_session, reset_session


# ───────────────────────── daemon (camino rápido) ─────────────────────────
def _claude_daemon_up() -> bool:
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.3)
        s.connect(str(CLAUDE_SOCK))
        s.close()
        return True
    except OSError:
        return False


def prewarm_claude() -> None:
    """Spawnea el daemon de Claude si no corre. NO bloquea: el proceso `claude`
    carga plugins/sesión en paralelo mientras grabás/transcribís -> sin cold-start."""
    if _claude_daemon_up():
        return
    try:
        subprocess.Popen(
            [sys.executable, str(CLAUDE_DAEMON)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True, env={**os.environ},
        )
        log("claude daemon spawned (prewarm)")
    except OSError as e:
        log(f"claude daemon spawn fail: {e}")


def reset_claude() -> None:
    """Resetea la sesión. Si el daemon está vivo, le pide reset (nueva sesión +
    respawn). Si no, resetea el archivo local (el próximo spawn la toma)."""
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(10.0)
        s.connect(str(CLAUDE_SOCK))
        s.sendall(b'{"reset": true}\n')
        s.recv(256)
        s.close()
        log("claude daemon reset")
    except OSError:
        reset_session()


def _ask_via_daemon(prompt: str, on_first_token) -> "Iterator[str]":
    """Cliente del daemon. Yieldea text_deltas. Devuelve (via return) True si el
    daemon manejó el turno, False si hay que caer al fallback one-shot."""
    try:
        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        conn.settimeout(3.0)
        conn.connect(str(CLAUDE_SOCK))
    except OSError:
        return False
    try:
        conn.sendall((json.dumps({"prompt": prompt}) + "\n").encode())
        conn.settimeout(1.0)   # recv corto -> permite chequear _cancel entre chunks
        buf = b""
        first = False
        any_delta = False
        deadline = time.time() + CLAUDE_TIMEOUT_S
        while True:
            if _cancel.is_set():
                return True   # cancelado: el daemon drena solo; turno "manejado"
            if time.time() > deadline:
                log("daemon claude timeout -> no re-mando (el daemon tiene su propio timeout; evito turno+memoria duplicados)")
                return True   # handled: NO caer a one-shot (re-enviar duplicaría respuesta y memoria)
            try:
                chunk = conn.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                return any_delta   # socket cerrado: si ya habló -> ok; si no -> fallback
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    o = json.loads(raw.decode())
                except ValueError:
                    continue
                if "delta" in o:
                    if not first:
                        if on_first_token:
                            try:
                                on_first_token()
                            except Exception:
                                pass
                        first = True
                    any_delta = True
                    yield o["delta"]
                elif o.get("done"):
                    touch_session()
                    log("claude daemon turn OK")
                    return True
                elif "error" in o:
                    log(f"claude daemon error: {o['error']}")
                    return any_delta   # sin deltas -> False -> fallback one-shot
    finally:
        try:
            conn.close()
        except OSError:
            pass


# ───────────────────────── one-shot (fallback) ─────────────────────────
def _ask_oneshot(
    prompt: str,
    on_first_token: "Callable[[], None] | None",
    screenshot_path: "Path | None",
) -> Iterator[str]:
    """Spawn `claude -p` de un solo turno (lo que anduvo siempre). Maneja imagen
    y el fallback --resume/--session-id. Es el camino seguro si el daemon falla."""
    has_image = screenshot_path is not None and screenshot_path.exists()
    session_id, is_new = get_active_session_id()
    first_flag = "--session-id" if is_new else "--resume"
    second_flag = "--resume" if is_new else "--session-id"

    stdin_payload: "str | None" = None
    if has_image:
        try:
            img_b64 = base64.b64encode(screenshot_path.read_bytes()).decode("ascii")
            stdin_payload = json.dumps({
                "type": "user",
                "message": {"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_b64}},
                    {"type": "text", "text": prompt},
                ]},
            }) + "\n"
        except Exception as e:
            log(f"image encode EXC: {type(e).__name__}: {e}, text-only")
            has_image = False

    def _spawn(flag: str) -> subprocess.Popen:
        args = build_claude_base_args(session_id, flag)   # fuente única (compartida con el daemon)
        if has_image:
            args += ["-p", "--input-format", "stream-json"]
            return subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, bufsize=1,
                                    start_new_session=True)   # grupo propio -> cancel mata el árbol (no orfana claude-mem)
        args += ["-p", prompt]
        return subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, bufsize=1, start_new_session=True)

    for attempt, flag in enumerate((first_flag, second_flag)):
        try:
            proc = _spawn(flag)
        except FileNotFoundError:
            log("claude FATAL: binary not found in PATH")
            return
        except Exception as e:
            log(f"claude SPAWN EXC: {type(e).__name__}: {e}")
            return

        if stdin_payload is not None and proc.stdin is not None:
            try:
                proc.stdin.write(stdin_payload)
                proc.stdin.flush()
                proc.stdin.close()
            except Exception as e:
                log(f"stdin write EXC: {type(e).__name__}: {e}")
        text_received = False
        assert proc.stdout is not None
        deadline = time.time() + CLAUDE_TIMEOUT_S
        for raw_line in proc.stdout:
            if _cancel.is_set():
                log("stream cancelled, breaking")
                break
            if time.time() > deadline:
                log(f"claude STREAM TIMEOUT after {CLAUDE_TIMEOUT_S}s")
                break
            line = raw_line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") != "stream_event":
                continue
            event = obj.get("event", {})
            if event.get("type") != "content_block_delta":
                continue
            delta = event.get("delta", {})
            if delta.get("type") != "text_delta":
                continue
            text = delta.get("text", "")
            if text:
                if not text_received:
                    if on_first_token is not None:
                        try:
                            on_first_token()
                        except Exception:
                            pass
                    text_received = True
                yield text
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()

        if _cancel.is_set():
            return

        err = ""
        try:
            if proc.stderr is not None:
                err = proc.stderr.read() or ""
        except Exception:
            pass

        if proc.returncode == 0 and text_received:
            touch_session()
            log("claude stream done OK (one-shot)")
            return

        log(f"claude one-shot err rc={proc.returncode} flag={flag} stderr={err[:300]} text={text_received}")
        low = err.lower()
        retryable = ("no conversation found" in low or "not found" in low
                     or "does not exist" in low or "already in use" in low)
        if attempt == 0 and retryable:
            log(f"retry one-shot with {second_flag}")
            continue
        return


# ───────────────────────── dispatcher ─────────────────────────
def ask_claude_stream(
    prompt: str,
    on_first_token: "Callable[[], None] | None" = None,
    screenshot_path: "Path | None" = None,
) -> Iterator[str]:
    """Stream de text_deltas de Claude. Daemon caliente primero; si no, one-shot.
    Las imágenes van directo al one-shot (más simple/probado para multimodal)."""
    has_image = screenshot_path is not None and screenshot_path.exists()
    log(f"claude prompt{' [+img]' if has_image else ''}: {prompt!r}")

    if not has_image:
        handled = yield from _ask_via_daemon(prompt, on_first_token)
        if handled:
            return
        log("daemon claude no disponible -> fallback one-shot")

    yield from _ask_oneshot(prompt, on_first_token, screenshot_path)
