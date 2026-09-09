"""Dispatch del agente al room: pedirle a LiveKit que meta al worker en la sala.

POR QUÉ EXISTE ESTE MÓDULO
--------------------------
El dispatch AUTOMÁTICO (worker sin `agent_name`) despacha cuando el room SE CREA. Ahí estaba
el bug: si la pestaña del orbe ya estaba abierta, el cliente reconectaba apenas volvía
`livekit-server` y creaba el room ~2s ANTES de que el worker terminara de registrarse. Sin
evento de creación pendiente, el agente no entraba nunca y Win+Z moría con `FileNotFoundError`
sobre el socket de control. Medido: room 00:32:41.106, worker 00:32:43.226. `saga-ctl restart`
con el orbe abierto fallaba SIEMPRE, no de a ratos.

POR QUÉ NO SE HACE POR TOKEN
----------------------------
El camino "elegante" sería firmar el dispatch en el JWT (`RoomConfiguration.agents`), que es lo
que documenta LiveKit y lo que hace `lk token create --agent`. NO SIRVE ACÁ, y el server lo dice
con todas las letras:

    not dispatching agent job since no worker is available
      {"agentName": "saga", "jobType": "JT_PARTICIPANT", "room": "saga"}

El dispatch por token pide un job `JT_PARTICIPANT`, y el SDK de Python sólo sabe registrar
workers `JT_ROOM` o `JT_PUBLISHER` (`ServerType` no tiene PARTICIPANT). O sea: el token pide un
tipo de trabajo que ningún worker de este SDK puede atender. Verificado contra livekit-agents
1.6.10; si algún día aparece `ServerType.PARTICIPANT`, esto se puede simplificar.

La API de dispatch sí crea un job `JT_ROOM`, que es el que nuestro worker atiende.
"""

import asyncio
import os

from .config import LIVEKIT_AGENT_NAME, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, LIVEKIT_ROOM, LIVEKIT_URL
from .runtime import log


def _http_url() -> str:
    """La API REST va por http(s), no por el ws(s) del signaling."""
    return LIVEKIT_URL.replace("wss://", "https://").replace("ws://", "http://")


async def _agent_in_room(lk, room: str) -> bool:
    """¿Ya hay un agente adentro? `kind == 4` (AGENT) en el modelo de participantes."""
    from livekit import api

    try:
        ps = await lk.room.list_participants(api.ListParticipantsRequest(room=room))
    except Exception:      # noqa: BLE001 - el room puede no existir todavía: no hay agente
        return False
    return any(getattr(p, "kind", None) == 4 for p in ps.participants)


async def _ensure_async(room: str, agent_name: str) -> bool:
    from livekit import api

    lk = api.LiveKitAPI(_http_url(), LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
    try:
        if await _agent_in_room(lk, room):
            return False           # ya está adentro: pedir otro dispatch duplicaría el agente
        await lk.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(room=room, agent_name=agent_name)
        )
        log(f"[dispatch] agente '{agent_name}' pedido para el room '{room}'")
        return True
    finally:
        await lk.aclose()


def ensure_agent(room: str = LIVEKIT_ROOM, agent_name: str = LIVEKIT_AGENT_NAME) -> bool:
    """Mete al agente en el room si no está. Devuelve True si hubo que pedirlo.

    Es SÍNCRONA a propósito: la llama `orb_server`, que es un ThreadingHTTPServer de stdlib.
    Nunca levanta: si LiveKit no contesta, el peor caso es el de antes (agente ausente) y el
    orbe igual tiene que poder servir su página.

    Idempotente: si el agente ya está adentro no hace nada, así recargar la pestaña no
    acumula agentes en la sala.
    """
    if not LIVEKIT_API_KEY or not LIVEKIT_API_SECRET:
        return False
    try:
        return asyncio.run(_ensure_async(room, agent_name))
    except Exception as e:  # noqa: BLE001 - degradar, nunca romper el pedido del cliente
        log(f"[dispatch] no se pudo pedir el agente: {type(e).__name__}: {e}")
        return False


if __name__ == "__main__":   # `python -m vc.dispatch` para probar a mano
    from dotenv import load_dotenv

    from .config import ENV_FILE

    load_dotenv(ENV_FILE)
    print("dispatch pedido" if ensure_agent() else "no hizo falta (o falló, ver log)")
    raise SystemExit(0 if os.environ.get("LIVEKIT_API_KEY") else 1)
