# Unit Dependency Matrix — Ciclo 9

## Orden de ejecución: U1 → U2 → U3 (secuencial estricto)

```
  U1 (tests + CI)  ──────►  U2 (orb_server)  ──────►  U3 (permisos)
  riesgo BAJO               riesgo MEDIO              riesgo ALTO
  no toca runtime           superficie HTTP           corazón del agente
       │                         │                         │
       └── PR #1 → main          └── PR #2 → main          └── PR #3 → main
           (red lista)               (validado en vivo)        (gate de latencia)
```

## Matriz

| Unidad | Depende de | Tipo de dependencia | ¿Bloqueante? |
|---|---|---|---|
| **U1** | — | — | No |
| **U2** | U1 | **De verificación**, no técnica. U2 *podría* escribirse sin U1, pero entonces no habría tests que detecten si rompe el routing o la auth. | **Sí** (por decisión de proceso) |
| **U3** | U1, U2 | **De verificación + de riesgo.** U3 es el cambio que puede romper el flujo de voz. Llega cuando la red de tests existe y la superficie HTTP ya está limpia y validada en vivo. | **Sí** (por decisión de proceso) |

**Nota importante**: ninguna dependencia es técnica-obligatoria (los tres cambios son independientes a nivel de código). El orden es una **decisión de gestión de riesgo**: no se toca lo peligroso sin red. Invertirlo sería tocar el corazón del agente sin un solo test que avise de una regresión.

## Puntos de coordinación

| # | Punto | Unidad | Riesgo si se rompe |
|---|---|---|---|
| **C1** | `orb/orb.html` ↔ `orb/orb_server.py` — si el servidor exige token, el cliente **debe** mandarlo | **U2** | **El orbe no conecta → saga queda muda.** Los dos cambios son atómicos: se hacen y se validan juntos. |
| **C2** | `vc/config.py` es la **fuente única** de `build_claude_base_args()` | **U3** | `claude_daemon.py` y `vc/claudecli.py` heredan el cambio de permisos **sin tocarlos**. Ventaja: un solo punto de cambio. Riesgo: un error acá afecta a los dos consumidores a la vez. |
| **C3** | `vc/config.py` lo tocan **U2** (generación del `ORB_TOKEN`) y **U3** (flags + settings + prompt) | U2, U3 | Conflicto de merge menor. Mitigado por el orden secuencial (U2 mergea antes de que U3 empiece). |

## Estrategia de merge (Q1=A)

Un PR por unidad. Cada PR:
1. Se verifica en estático (suite + lint + typecheck + `pip-audit`).
2. Se valida **en vivo** por el usuario cuando toca runtime (U2, U3).
3. Se mergea a `main` solo tras el OK explícito.

**Ventaja concreta**: si U3 falla el gate de latencia (G1) y hay que rebotar a `dontAsk`, U1 (la red de tests) y U2 (la superficie HTTP cerrada) **ya están en `main`** y no se pierden.

## Rollback

Por git (NFR3: no hay toggle de apagado de la seguridad). Cada unidad es un PR revertible de forma independiente. La rama `feature/security-testing-workflow` es la red durante el desarrollo.
