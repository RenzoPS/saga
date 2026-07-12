# U1 — Infra room · Generation Summary (Ciclo 4)

> Código generado para U1. Brownfield: se modificaron archivos existentes + se crearon los nuevos de infra.

> **⚠️ ACTUALIZADO 2026-06-23 — PIVOT Docker → binario nativo.** Lo de abajo (docker-compose.yml) quedó
> OBSOLETO. En el Build&Test de integración el WebRTC fallaba con `dtls timeout` por el NAT de Docker sobre
> localhost. Fix: el server corre como **binario nativo** `~/.local/bin/livekit-server` (tarball oficial
> v1.13.1, checksum SHA256 verificado, fuera del repo). `docker-compose.yml` ELIMINADO. `livekit.yaml` ahora:
> signaling loopback + `udp_port` único 7882 + `node_ip` por env `NODE_IP` (IP LAN auto-detectada; LiveKit no
> bindea UDP a loopback). Ver el detalle en aidlc-state.md (Build&Test parcial Ciclo 4). El resto de U1
> (token endpoint, constantes config, keys) sigue igual y válido.

## Archivos creados
- **`docker-compose.yml`** — servicio `livekit-server`, imagen `livekit/livekit-server:v1.13.1` (última
  versión específica verificada en Docker Hub al 2026-06-23; NO `latest`, NO menor). `network_mode: host`
  + bind loopback (vía yaml) = local-only. Keys inyectadas como `LIVEKIT_KEYS` desde `.env.local`.
- **`livekit.yaml`** — config del server (sin secretos, versionable): puerto 7880, `bind_addresses: [127.0.0.1]`,
  RTC con `use_external_ip: false` + `node_ip: 127.0.0.1` (candidatos ICE loopback), single-node, logging.

## Archivos modificados
- **`vc/config.py`** — (1) carga `.env.local` con python-dotenv al importar (idempotente) → cualquier
  importador (worker U2, orb_server `/token`) ve las keys, no solo el agente. (2) Constantes del transporte
  room: `LIVEKIT_URL` (default `ws://127.0.0.1:7880`), `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `LIVEKIT_ROOM`
  (default `saga`).
- **`orb/orb_server.py`** — endpoint `GET /token?identity=&room=` → JSON `{url, token, room}`. Mintea el JWT
  con `livekit.api.AccessToken` + `VideoGrants(room_join=True, room=...)`, firmado con `LIVEKIT_API_SECRET`.
  Import de `livekit.api` **lazy** (dentro del handler) → el orbe en modo console no carga la dep. 500 si
  faltan keys o falla el mint. Docstring del módulo + `import json` agregados.
- **`.env.local`** (gitignored) — `LIVEKIT_URL`, `LIVEKIT_ROOM`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`
  generadas (python `secrets`) y escritas sin volcar el secreto a logs. chmod 600.

## Deps
- `livekit.api` ya importable en el venv (transitivo de `livekit-agents`) → `pyproject.toml` sin cambios.

## Verificación
| Check | Resultado |
|---|---|
| `docker compose --env-file .env.local config -q` | ✅ válido |
| `py_compile orb/orb_server.py vc/config.py` | ✅ |
| `config.LIVEKIT_*` expuestas (key/secret seteadas) | ✅ (sin imprimir secreto) |
| Mint + verify round-trip del JWT (identity/room/room_join) | ✅ JWT 316 chars, claims correctos |
| Boot del server + `curl 127.0.0.1:7880` | ⏳ **PENDIENTE**: daemon Docker apagado (requiere `sudo systemctl start docker`) |
| Modo console intacto | ✅ (U1 es aditivo, no toca runtime de audio) |

## Pendiente para cerrar la verificación de U1 (acción del usuario)
```bash
sudo systemctl start docker            # daemon Docker (unit disabled+inactive)
cd ~/.local/share/saga
docker compose --env-file .env.local up -d
curl http://127.0.0.1:7880/            # server vivo
```

## Notas / decisiones
- **Local-only**: `network_mode: host` + `bind_addresses: 127.0.0.1`. El browser cliente y el worker corren
  en la misma máquina → WebRTC loopback (~ms), nada expuesto a la LAN. Cumple el constraint de privacidad.
- **Secretos fuera del repo**: `livekit.yaml` y `docker-compose.yml` son versionables; las keys solo viven
  en `.env.local`. El compose las lee con `--env-file .env.local` (ojo: docker compose NO lee `.env.local`
  por default, hay que pasar `--env-file`; U6/saga-ctl debe usar ese flag).
- **Habilita**: U2 (worker `start --url ws://127.0.0.1:7880`), U3 (cliente pide `/token` y se une), U6 (saga-ctl).
