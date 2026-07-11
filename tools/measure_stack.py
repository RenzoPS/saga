#!/usr/bin/env python3
"""measure_stack.py — observabilidad de atribución para el spike del Ciclo 5.

Responde "¿QUÉ pieza consume?" cuando se carga el stack de plugins en el daemon de voz.
Camina el árbol de procesos del daemon de Claude (claude_daemon.py -> claude CLI -> MCPs
nietos) y atribuye RSS + %CPU a cada proceso, etiquetando los MCPs por su cmdline. Además
extrae del saga.log el boot del daemon (incluye stack=off|full + plugins apagados) y marcas de TTFT.

Por TIPO de pieza (recordatorio, ver how-to-measure.md):
  - MCPs   -> PROCESOS separados -> RSS/CPU directos (lo que mide este script).
  - Boot lento/cuelgue -> `claude --debug` (qué MCP timeoutea); acá se ve el boot del saga.log.
  - Skills -> tokens de contexto (no procesos) -> se ven como TTFT más alto, no como RSS.
  - Hooks  -> latencia por turno -> delta de TTFT en el saga.log.

Solo lectura (/proc + saga.log). No toca nada. Degrada si el daemon no corre.

Uso:
  python tools/measure_stack.py                # snapshot único
  python tools/measure_stack.py --watch 3      # cada 3s hasta Ctrl-C
  python tools/measure_stack.py --cpu-interval 1.0
"""

import os
import sys
import time
import argparse
from pathlib import Path

PROC = Path("/proc")
CLK_TCK = os.sysconf("SC_CLK_TCK")
DEFAULT_LOG = Path.home() / ".local/share/saga/saga.log"

# Etiquetas legibles por substring del cmdline (orden = prioridad).
_LABELS = [
    ("claude_daemon.py", "saga daemon (claude_daemon.py)"),
    ("chroma-mcp", "chroma-mcp  [claude-mem vector DB]"),
    ("mcp-server.cjs", "claude-mem mcp-server"),
    ("playwright", "playwright-mcp  [+Chromium]"),
    ("exa-mcp", "exa-mcp"),
    ("context7", "context7-mcp"),
    ("mcpvault", "mcpvault  [obsidian]"),
    ("modelcontext", "mcp (genérico)"),
]


def _read(pid: str, name: str) -> str:
    try:
        return (PROC / pid / name).read_text()
    except (OSError, ValueError):
        return ""


def _cmdline(pid: str) -> str:
    raw = ""
    try:
        raw = (PROC / pid / "cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="replace").strip()
    except OSError:
        pass
    if not raw:  # kernel thread / sin cmdline -> usa comm
        c = _read(pid, "comm").strip()
        return f"[{c}]" if c else "?"
    return raw


def _rss_kb(pid: str) -> int:
    for line in _read(pid, "status").splitlines():
        if line.startswith("VmRSS:"):
            try:
                return int(line.split()[1])
            except (IndexError, ValueError):
                return 0
    return 0


def _cpu_ticks(pid: str) -> int:
    """utime + stime en ticks (campos 14,15 de /proc/pid/stat)."""
    stat = _read(pid, "stat")
    if not stat:
        return 0
    rp = stat.rfind(")")  # el comm puede tener espacios/paréntesis -> partir después del último ')'
    fields = stat[rp + 2:].split() if rp != -1 else stat.split()
    try:
        return int(fields[11]) + int(fields[12])  # utime, stime (0-indexados tras el split post-')')
    except (IndexError, ValueError):
        return 0


def _all_pids():
    return [p.name for p in PROC.iterdir() if p.name.isdigit()]


def _ppid(pid: str) -> str:
    for line in _read(pid, "status").splitlines():
        if line.startswith("PPid:"):
            return line.split()[1]
    return "0"


def _label(cmd: str) -> str:
    low = cmd.lower()
    for key, lab in _LABELS:
        if key in low:
            return lab
    toks = cmd.split()
    if toks:
        base = os.path.basename(toks[0].rstrip(":"))
        if base == "claude" or any(os.path.basename(t) == "claude" for t in toks[:2]):
            return "claude CLI (daemon child)"
        return base[:32]
    return "?"


def find_daemon_pid(pids):
    for pid in pids:
        if "claude_daemon.py" in _cmdline(pid):
            return pid
    return None


def descendants(root, child_map):
    out, stack = [], [root]
    while stack:
        cur = stack.pop()
        for ch in child_map.get(cur, []):
            out.append(ch)
            stack.append(ch)
    return out


def snapshot(cpu_interval: float):
    pids = _all_pids()
    child_map = {}
    for pid in pids:
        child_map.setdefault(_ppid(pid), []).append(pid)

    root = find_daemon_pid(pids)
    if not root:
        print("daemon de Claude NO corre (claude_daemon.py no encontrado).")
        print("Arrancá saga (ej. CLAUDE_PLUGINS=1 saga-ctl start) y reintentá.")
        return

    tree = [root] + descendants(root, child_map)

    t0 = {pid: _cpu_ticks(pid) for pid in tree}
    time.sleep(cpu_interval)
    rows = []
    for pid in tree:
        if not (PROC / pid).exists():
            continue
        dt = _cpu_ticks(pid) - t0.get(pid, 0)
        pct = (dt / CLK_TCK) / cpu_interval * 100.0  # estilo top (por-core, puede pasar 100%)
        rows.append((pid, _rss_kb(pid) / 1024.0, pct, _label(_cmdline(pid))))

    rows.sort(key=lambda r: r[1], reverse=True)
    tot_rss = sum(r[1] for r in rows)
    tot_cpu = sum(r[2] for r in rows)

    print(f"=== árbol del daemon (root pid {root}) — {len(rows)} procesos ===")
    print(f"{'PID':>7}  {'RSS_MB':>8}  {'%CPU':>6}  PIEZA")
    for pid, rss, cpu, lab in rows:
        print(f"{pid:>7}  {rss:>8.1f}  {cpu:>6.1f}  {lab}")
    print(f"{'TOTAL':>7}  {tot_rss:>8.1f}  {tot_cpu:>6.1f}")
    try:
        la = os.getloadavg()
        print(f"loadavg sistema: {la[0]:.2f} {la[1]:.2f} {la[2]:.2f}  (ncpu={os.cpu_count()})")
    except OSError:
        pass


def tail_log(log: Path, n: int = 12):
    if not log.exists():
        print(f"(saga.log no existe en {log})")
        return
    try:
        lines = log.read_text(errors="replace").splitlines()
    except OSError as e:
        print(f"(no se pudo leer saga.log: {e})")
        return
    hits = [l for l in lines if ("spawned" in l) or ("stack=" in l)
            or ("ttft" in l.lower()) or ("TTFT" in l) or ("primer token" in l.lower())]
    print(f"=== saga.log: boot/stack/TTFT (últimas {n}) ===")
    for l in hits[-n:]:
        print("  " + l)
    if not hits:
        print("  (sin líneas de boot/stack/TTFT todavía)")


def main() -> int:
    ap = argparse.ArgumentParser(description="Atribución de RAM/CPU del stack del daemon de Claude (Ciclo 5).")
    ap.add_argument("--watch", type=float, metavar="SEC", help="repetir cada SEC segundos (Ctrl-C para salir)")
    ap.add_argument("--cpu-interval", type=float, default=0.5, help="ventana para muestrear %%CPU (default 0.5s)")
    ap.add_argument("--log", type=Path, default=DEFAULT_LOG, help="ruta del saga.log")
    args = ap.parse_args()

    def once():
        snapshot(args.cpu_interval)
        print()
        tail_log(args.log)

    if args.watch:
        try:
            while True:
                print("\n" + "=" * 64 + f"  {time.strftime('%H:%M:%S')}")
                once()
                time.sleep(args.watch)
        except KeyboardInterrupt:
            return 0
    else:
        once()
    return 0


if __name__ == "__main__":
    sys.exit(main())
