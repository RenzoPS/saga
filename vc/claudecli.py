"""Invocación al CLI de Claude: spawnea `claude` en modo stream-json y emite
los text_delta. Maneja sesión (--resume/--session-id con fallback) e imagen."""

import base64
import json
import time
import subprocess
from pathlib import Path
from typing import Callable, Iterator

from .config import (
    CLAUDE_MODEL,
    CLAUDE_FAST_FLAGS,
    CLAUDE_SKIP_PERMISSIONS,
    CLAUDE_TIMEOUT_S,
)
from .runtime import log, _cancel, set_current_proc
from .session import get_active_session_id, touch_session


def ask_claude_stream(
    prompt: str,
    on_first_token: "Callable[[], None] | None" = None,
    screenshot_path: "Path | None" = None,
) -> Iterator[str]:
    """Stream text_delta events de Claude CLI. Maneja --resume/--session-id fallback.
    Si screenshot_path es dado, manda imagen + texto via --input-format stream-json."""
    has_image = screenshot_path is not None and screenshot_path.exists()
    log(f"claude prompt{' [+img]' if has_image else ''}: {prompt!r}")
    system = (
        "Estas hablando, no escribiendo. Tu respuesta sale por parlante (TTS multilingue "
        "que pronuncia bien anglicismos, numeros, simbolos y siglas; no te preocupes por fonetizar). "
        "\n\n"
        "Reglas firmes:\n"
        "- Texto plano. Nada de markdown: sin asteriscos, sin backticks, sin listas con guiones o numeros, sin headers.\n"
        "- Espanol rioplatense: vos, dale, che, fijate.\n"
        "- Largo proporcional: pregunta corta = respuesta corta. Tono conversacional, directo, sin floreos.\n"
        "- Si no podes responder por falta de datos o tools, una sola frase corta. No listes alternativas ni te disculpes.\n"
        "\n"
        "Estilo:\n"
        "Hablas como si le contaras algo a un amigo en un cafe. Nada de 'primero, segundo, tercero', "
        "'aspectos clave', 'puntos importantes', 'cabe destacar'. Frases fluidas, conectadas. "
        "Conectores naturales: 'asi que', 'entonces', 'igual', 'mira', 'fijate'. "
        "Si explicas algo tecnico, lo contas como historia, no como manual."
    )
    session_id, is_new = get_active_session_id()
    first_flag = "--session-id" if is_new else "--resume"
    second_flag = "--resume" if is_new else "--session-id"

    # Si hay imagen, pre-armo el JSON multimodal para stdin.
    stdin_payload: "str | None" = None
    if has_image:
        assert screenshot_path is not None
        try:
            img_bytes = screenshot_path.read_bytes()
            img_b64 = base64.b64encode(img_bytes).decode("ascii")
            stdin_payload = (
                json.dumps(
                    {
                        "type": "user",
                        "message": {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/png",
                                        "data": img_b64,
                                    },
                                },
                                {"type": "text", "text": prompt},
                            ],
                        },
                    }
                )
                + "\n"
            )
        except Exception as e:
            log(f"image encode EXC: {type(e).__name__}: {e}, falling back to text-only")
            has_image = False
            stdin_payload = None

    def _spawn(flag: str) -> subprocess.Popen:
        args = [
            "claude",
            "--model",
            CLAUDE_MODEL,
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--append-system-prompt",
            system,
            flag,
            session_id,
        ]
        args.extend(CLAUDE_FAST_FLAGS)
        if CLAUDE_SKIP_PERMISSIONS:
            args.append("--dangerously-skip-permissions")
        if has_image:
            args.extend(["-p", "--input-format", "stream-json"])
            return subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        args.extend(["-p", prompt])
        return subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    for attempt, flag in enumerate((first_flag, second_flag)):
        try:
            proc = _spawn(flag)
        except FileNotFoundError:
            log("claude FATAL: binary not found in PATH")
            return
        except Exception as e:
            log(f"claude SPAWN EXC: {type(e).__name__}: {e}")
            return

        set_current_proc(proc)
        # Si hay stdin payload (modo imagen), escribirlo y cerrar stdin.
        if stdin_payload is not None and proc.stdin is not None:
            try:
                proc.stdin.write(stdin_payload)
                proc.stdin.flush()
                proc.stdin.close()
            except Exception as e:
                log(f"stdin write EXC: {type(e).__name__}: {e}")
        text_received = False
        try:
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
        finally:
            set_current_proc(None)

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
            log("claude stream done OK")
            return

        log(f"claude stream err rc={proc.returncode} flag={flag} stderr={err[:400]} text_received={text_received}")
        low = err.lower()
        retryable = (
            "no conversation found" in low
            or "not found" in low
            or "does not exist" in low
            or "already in use" in low
        )
        if attempt == 0 and retryable:
            log(f"retry stream with {second_flag}")
            continue
        return
