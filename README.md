# po-intake-mcp

Servidor MCP que lleva órdenes de compra desde el correo hasta un **pedido en borrador validado**, sin que el modelo escriba nunca en el ERP.

> El modelo propone. El código valida. Una persona aprueba.

Todos los clientes, artículos, precios y correos de `data/` son inventados.

## Flujo

```
correo (.eml) -> clasificación -> extracción -> reglas en código -> staging -> aprobación -> erp_outbox/
```

1. **Clasificación:** ¿es una OC?, ¿de qué cliente (por dominio del remitente)?, ¿en qué formato?
2. **Extracción, lo más barato primero:** CSV o Excel con código; formato conocido con plantilla; formato desconocido con un LLM, que viene apagado (`PO_LLM=off`). Si el LLM está apagado, la orden va a la cola de excepciones; no se adivina nada.
3. **Reglas en código:** cliente conocido, SKU, unidad, cantidad mínima, múltiplo de empaque, precio dentro del ±2 % de la lista, plazo de entrega, total y duplicados. Las reglas corren igual aunque haya extraído el LLM: el modelo no decide.
4. **Staging:** cada orden queda como borrador o como excepción con su motivo.
5. **Aprobación:** una persona aprueba o rechaza, y queda registrado quién y por qué.
6. **`erp_outbox/`:** `approve_order` solo deja un JSON neutro. El adaptador de NetSuite o SAP es una pieza aparte, la única que cambia con el ERP. Ninguna herramienta escribe en el ERP.

**Trazabilidad por capas,** como en OneLake:
- `bronze/`: el `.eml` original, identificado por su SHA-256.
- `silver/`: cada orden con su extracción, el método, el modelo y el resultado de cada regla.
- `gold/`: solo las órdenes aprobadas.

## Herramientas MCP

| Herramienta | Qué hace |
|---|---|
| `list_inbox` | Lista los correos con remitente, asunto y adjuntos, y si ya se procesaron |
| `process_email` / `process_inbox` | Clasifica, extrae, valida y deja cada orden como borrador o excepción |
| `list_exceptions` | La cola de trabajo de una persona, con el motivo de cada excepción |
| `get_order` | El registro completo, incluido el historial |
| `revalidate_order` | Una persona corrige campos y las reglas vuelven a correr |
| `approve_order` / `reject_order` | Aprueba o rechaza, dejando quién lo hizo y por qué |
| `metrics` | Cantidades por estado y por método de extracción, tasa de órdenes sin intervención, llamadas al LLM y excepciones por regla |

## Demo con el inbox de ejemplo

| Correo | Resultado | Motivo |
|---|---|---|
| 01 Lácteos, OC en el cuerpo del correo | **borrador** | pasa todas las reglas |
| 02 Snacks, CSV adjunto | excepción | 22 millares no es múltiplo de 5 |
| 03 Café, PDF con formato conocido | excepción | precio un 8 % sobre la lista |
| 04 Remitente desconocido, PDF libre | excepción | formato desconocido y cliente desconocido |
| 05 Lácteos, reenvío de la misma OC | excepción | duplicado |
| 06 Consulta de stock | ignorado | no es una OC |

## Uso

```bash
uv sync --all-groups
uv run pytest -q          # 13 pruebas, incluida una que levanta el servidor real por stdio
uv run po-intake-mcp      # servidor MCP por stdio
```

En Claude Code:

```bash
claude mcp add po-intake -- uv --directory /ruta/a/po-intake-mcp run po-intake-mcp
```

LLM opcional, solo para formatos desconocidos:

```bash
uv sync --extra llm
PO_LLM=on PO_LLM_MODEL=claude-opus-5-5 uv run po-intake-mcp
```

Usa salida estructurada con un JSON Schema, así que la respuesta siempre tiene la forma esperada. El modelo se cambia con `PO_LLM_MODEL`, para usar el más barato que alcance la precisión medida.

## Qué cambia en producción

| Demo | Producción |
|---|---|
| Archivos `.eml` en `data/inbox/` | Microsoft Graph sobre un buzón compartido |
| CSV de maestros | Vista de solo lectura del ERP o de Fabric |
| `staging/` local | Lakehouse en OneLake (bronze, silver y gold) y Power BI sobre gold |
| `erp_outbox/` | Adaptador de NetSuite o SAP con su propia autenticación |
