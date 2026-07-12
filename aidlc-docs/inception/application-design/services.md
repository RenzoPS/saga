# Services / Orquestación — Ciclo 4 (modo room)

## saga-ctl (orquestador) — se amplía
Hoy levanta: agente (console) + claude_daemon + orb_server + monitor.
En modo room pasa a levantar y monitorear (con readiness por pieza):

1. **livekit-server** (Docker) — primero. Readiness: puerto del server responde (healthz / ws).
2. **claude_daemon** — cerebro caliente (igual que hoy).
3. **saga-worker** (`lk/agent.py start --url ws://localhost:7880 ...`) — se registra en el server, espera jobs.
   Readiness: worker registrado + conectado.
4. **orb_server** — sirve el orbe + endpoint `/token`. (igual que hoy + token).
5. **Abrir el browser cliente** (orbe) — se conecta al room con el token → publica mic, recibe TTS.
   Al unirse el cliente, el server despacha el job → el worker entra al room.

### Orden de readiness
```
livekit-server UP → claude_daemon HOT → saga-worker REGISTERED → orb_server UP (+token)
→ browser cliente JOINED room → worker dispatched → sesión lista
```

### Comandos (conceptual, no implementación)
- `saga-ctl start` → levanta los 5 en orden + readiness.
- `saga-ctl stop` → drena sesiones, baja worker, baja server (Docker), limpia.
- `saga-ctl status` → estado de cada pieza (server, worker registrado, daemon, orbe, cliente conectado).

## Fallback console (dev)
- Selección por env (ej. `SAGA_TRANSPORT=console|room`, default room).
- En console, saga-ctl NO levanta el server ni el token; usa el flujo actual. Para debug sin Docker.

## Servicios que NO cambian
- claude_daemon (cerebro caliente), orb_server (base), el modelo de wake, el system prompt.
