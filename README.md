# bnexia_graph — Grafo Operativo de Workflows n8n

> Sistema que transforma **exports JSON de workflows n8n** en un **grafo operativo
dirigido, queryable y de latencia sub-100ms**. Permite diagnosticar fallos, eval
uar impacto de cambios (blast radius) y exponer todo como **MCP tools** para age
ntes LLM.

---

## 📑 Tabla de Contenidos

- [Qué resuelve](#qué-resuelve)
- [Arquitectura](#arquitectura)
- [Componentes](#componentes)
- [Quick Start](#quick-start)
- [API Reference](#api-reference)
- [MCP Tools](#mcp-tools-sema4ai-actions)
- [Uso con Agentes LLM](#uso-con-agentes-llm)
- [Producción](#producción)
- [Estructura del Proyecto](#estructura-del-proyecto)
- [Contribuir](#contribuir)

---

## Qué resuelve

Cuando un workflow n8n falla, entender **qué lo causó** y **a quién afecta** sue
le implicar revisar manualmente flujos, logs y conexiones — un proceso lento y p
rono a errores.

**bnexia_graph** automatiza ese diagnóstico:

| Problema                             | Solución                                    |
|--------------------------------------|---------------------------------------------|
| ¿Qué nodos dependen del que falló?   | Blast radius — impacto en sub-100ms         |
| ¿Qué provocó el fallo?               | Contexto — upstream + downstream + categoría |
| ¿Cómo se conecta A con B?            | Ruta causal — camino más corto              |
| ¿Qué workflows comparten patrones?   | Detección automática de edges cruzados      |
| ¿Cómo consulto desde un agente?      | 6 MCP tools vía Sema4.ai Action Server      |

**0 llamadas a LLM** para construir el grafo. Parser 100% determinista. Queries
son traversales en RAM sobre NetworkX.

---

## Arquitectura

```
┌──────────────────────────────────────────────────────────────┐
│                  CAPA 1: INGESTA                              │
│  corpus/n8n_exports/ ─► graphify ─► graph.json               │
│  (JSONs n8n)       (parser det.)  (NetworkX DiGraph)          │
│                                                               │
│  ● Determinista (0 LLM)    ● SHA256 incremental             │
│  ● 268 nodos / 233 edges   ● Categorización automática        │
└────────────────────────┬─────────────────────────────────────┘
                         │ graph.json
                         ▼
┌──────────────────────────────────────────────────────────────┐
│                  CAPA 2: API (FastAPI :8090)                  │
│                                                               │
│  POST /diagnostic_context  → contexto completo del nodo       │
│  POST /blast_radius        → impacto cascada downstream       │
│  POST /path                → ruta causal más corta            │
│  POST /query               → búsqueda por texto (budget)      │
│  GET  /neighbors/{node}    → superficie de dependencias       │
│  GET  /admin/reload        → recarga grafo en caliente        │
└────────────────────────┬─────────────────────────────────────┘
                         │ HTTP
                         ▼
┌──────────────────────────────────────────────────────────────┐
│                  CAPA 3: MCP TOOLS (Sema4.ai)                 │
│                                                               │
│  graphify_build           → build completo / incremental      │
│  start_graph_api          → levanta FastAPI en background     │
│  graphify_full_pipeline   → one-shot: API + grafo + reload   │
│  get_diagnostic_context   → wrapper async POST /diagnostic…  │
│  calculate_blast_radius   → wrapper async POST /blast_radius  │
│  find_causal_path         → wrapper async POST /path         │
│                                                                 │
│  Expuesto como:  /api/mcp/  (streamable_http)                 │
└────────────────────────┬─────────────────────────────────────┘
                         │ MCP
                         ▼
┌──────────────────────────────────────────────────────────────┐
│                  CAPA 4: AGENTE LLM                           │
│                                                               │
│  Claude / GPT / Local ─► MultiServerMCPClient ─► bnexia-actions│
│  "Diagnostica el fallo en docx gen"                          │
──────────────────────────────────────────────────────────────
```

---

## Componentes

### 1. `graphify_n8n_standalone/` — Parser & Builder

| Característica     | Detalle                                                         |
|--------------------|-----------------------------------------------------------------|
| **Parser**         | Determinista. Nodos, conexiones y metadatos desde JSONs         |
| **Categorización** | trigger, api_call, ai_agent, transform, conditional, data_store, notification, data_processing, generic |
| **Edges cruzados** | Detecta patrones entre workflows (INFERRED, confidence 0.6)     |
| **Build incremental** | SHA256 cache — solo procesa archivos modificados              |
| **Reporte**        | `GRAPH_REPORT.md` con god nodes, huérfanos y leaf nodes         |

### 2. `graph_api/` — API de Consulta

- **Sin base de datos**: todo en RAM sobre `NetworkX.DiGraph`
- **Fuzzy matching**: no necesitas el nombre exacto del nodo
- **Hot reload**: `GET /admin/reload` sin reiniciar el servidor

### 3. `bnexia_actions/` — MCP Tools (Sema4.ai Action Server)

| Acción                   | Tipo   | Descripción                                      |
|--------------------------|--------|--------------------------------------------------|
| `graphify_build`         | sync   | Construye el grafo (completo o incremental)       |
| `start_graph_api`        | sync   | Levanta uvicorn con graph_api en background       |
| `graphify_full_pipeline` | sync   | One-shot: API + grafo + reload                   |
| `get_diagnostic_context` | async  | Wrapper de POST `/diagnostic_context`             |
| `calculate_blast_radius` | async  | Wrapper de POST `/blast_radius`                  |
| `find_causal_path`       | async  | Wrapper de POST `/path`                          |

---

## Quick Start

### Prerrequisitos

```bash
Python >= 3.10
pip install networkx fastapi uvicorn httpx
# Para MCP tools:
pip install sema4ai-actions
```

### Opción A: Uso directo (Capas 1 + 2)

#### 1. Preparar corpus

```bash
mkdir -p corpus/n8n_exports
# Colocar aquí los JSONs exportados de n8n
```

#### 2. Construir el grafo

```bash
# Build completo
python -m graphify_n8n_standalone corpus/n8n_exports

# Output esperado:
#   Procesados 10/10 archivos
#   Grafo: 268 nodos, 233 edges
#   Guardado en graphify-out/graph.json

# Build incremental (solo archivos cambiados)
python -m graphify_n8n_standalone corpus/n8n_exports --update
```

#### 3. Levantar API

```bash
cd graph_api
uvicorn server:app --host 0.0.0.0 --port 8090
# Grafo cargado: 268 nodos, 233 edges
```

#### 4. Consultar

```bash
# Contexto de diagnóstico (con fuzzy matching)
curl -s -X POST http://localhost:8090/diagnostic_context \
  -H "Content-Type: application/json" \
  -d '{"node": "docx gen"}'

# Blast radius
curl -s -X POST http://localhost:8090/blast_radius \
  -H "Content-Type: application/json" \
  -d '{"source": "MCP B-CONNECT -> MCP Server Trigger"}'

# Ruta causal entre nodos
curl -s -X POST http://localhost:8090/path \
  -H "Content-Type: application/json" \
  -d '{"source": "Nodo A", "target": "Nodo B"}'
```

### Opción B: Con Agente LLM (Capas 1 + 2 + 3 + 4)

#### 1. Iniciar Action Server

```bash
cd bnexia_actions
action-server start --port 8081 --auto-reload
# El servidor descubre automáticamente los 6 @actions
```

#### 2. Conectar desde tu agente

```python
from langchain_mcp_adapters.client import MultiServerMCPClient

async with MultiServerMCPClient({
    "bnexia-graph": {
        "url": "http://127.0.0.1:8081/api/mcp/",
        "transport": "streamable_http",
    }
}) as client:
    tools = client.get_tools()
    # Ahora el agente puede diagnosticar workflows en conversación natural
```

#### 3. Ejemplos de queries al agente

- "Diagnostica el fallo en el workflow de docx gen"
- "¿Qué impacto tiene si dejo de funcionar el trigger de B-Connect?"
- "Reconstruye el grafo con los datos más recientes"
- "¿Cómo se conecta el trigger de Odoo con el generador de informes?"

### Opción C: One-shot con MCP

El agente ejecuta `graphify_full_pipeline()` y tiene **todo listo en un solo
call**:

```json
// Input:
graphify_full_pipeline(corpus_path="/ruta/corpus/")

// Output:
{
  "status": "complete",
  "api": {"status": "started", "test_url": "http://127.0.0.1:8090/admin/reload"},
  "graph": {"status": "success", "nodes": 268, "edges": 233},
  "ready": true
}
```

---

## API Reference

Base URL: `http://<host>:8090`

| Endpoint             | Método | Payload                              | Uso                                           |
|----------------------|--------|--------------------------------------|-----------------------------------------------|
| `/diagnostic_context`| POST   | `{"node": "nombre"}`                 | Contexto completo: upstream, downstream, blast_radius, categoría |
| `/blast_radius`      | POST   | `{"source": "nombre_nodo"}`          | Impacto cascada de fallo o modificación       |
| `/path`              | POST   | `{"source": "A", "target": "B"}`     | Ruta causal más corta                         |
| `/query`             | POST   | `{"query": "texto", "budget": 500}`  | Búsqueda en nodos por texto (BFS con límite)  |
| `/neighbors/{node}`  | GET    | `?depth=1`                           | Dependencias en N hops                        |
| `/admin/reload`      | GET    | —                                    | Recarga graph.json sin reiniciar la API       |

### Respuesta típica: `/diagnostic_context`

```json
{
  "target_node": "docx gen -> When chat message received",
  "category": "trigger",
  "upstream": [],
  "downstream": ["docx gen -> MCP Tool: ..."],
  "blast_radius": ["nodo1", "nodo2", ...],
  "confidence": 1.0
}
```

### Respuesta típica: `/blast_radius`

```json
{
  "source": "MCP B-CONNECT -> MCP Server Trigger",
  "total_impacted": 45,
  "blast_radius": ["nodo1", "nodo2", ...],
  "direct_impact": ["nodo_afectado_1", "nodo_afectado_2"]
}
```

### Fuzzy Search

Todos los endpoints de diagnóstico aceptan búsqueda parcial:
- `"docx gen"` resuelve a `"docx gen -> When chat message received"`
- `"Bearer"` resuelve a nodos que contengan esa cadena

Si no hay coincidencia, el endpoint devuelve error con mensaje descriptivo.

---

## MCP Tools (Sema4.ai Actions)

Disponibles via `bnexia_actions/` package. Cada action tiene `@action` decorator
con docstring Google-style que se convierte en descripción MCP.

### Configuración

```yaml
# bnexia_actions/package.yaml
spec-version: v2
name: bnexia-actions
version: 0.2.0
dependencies:
  conda-forge:
    - python=3.12
    - pip
  pypi:
    - sema4ai-actions>=1.0.0,<2.0.0
    - httpx>=0.27.0,<1.0.0
    - networkx>=3.1
    - fastapi>=0.105.0
    - uvicorn>=0.25.0
```

### Environment Variables

| Variable          | Default              | Descripción                          |
|--------------------|---------------------------|----------------------------------------------|
| `GRAPH_API_URL`    | `http://127.0.0.1:8090`   | URL base de graph_api                        |

### Variables de entorno del builder

| Variable          | Default                     | Descripción                          |
|--------------------|-----------------------------|--------------------------------------|
| `CORPUS_DEFAULT`   | `corpus/n8n_exports/`      | Ruta al directorio con JSONs de n8n |
| `OUTPUT_DEFAULT`   | `graphify-out/`            | Directorio de salida del grafo      |

---

## Uso con Agentes LLM

### LangChain / LangGraph

```python
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_anthropic import ChatAnthropic
from langgraph.prebuilt import create_react_agent

async def run_diagnostic(query: str):
    async with MultiServerMCPClient({
        "bnexia-graph": {
            "url": "http://127.0.0.1:8081/api/mcp/",
            "transport": "streamable_http",
        },
        # Otros packages...
        # "docling-tools": { ... },
    }) as client:
        tools = client.get_tools()
        llm = ChatAnthropic(model="claude-sonnet-4-20250514").bind_tools(tools)
        agent = create_react_agent(llm, tools)
        result = await agent.ainvoke({"messages": [("human", query)]})
        return result["messages"][-1].content
```

### Multi-server (múltiples packages MCP)

```python
async with MultiServerMCPClient({
    "bnexia-graph": {
        "url": "http://127.0.0.1:8081/api/mcp/",
        "transport": "streamable_http",
    },
    "docling-tools": {
        "url": "https://abc.sema4ai.link/api/mcp/",
        "transport": "streamable_http",
    },
}) as client:
    all_tools = client.get_tools()
```

---

## Producción

### No usar `--expose` en producción

En lugar del tunnel de Sema4.ai, usar la API directamente:

```bash
# 1. API en puerto dedicado
cd graph_api
uvicorn server:app --host 127.0.0.1 --port 8090 --workers 2

# 2. Nginx reverse proxy (recomendado)
location /api/ {
    proxy_pass http://127.0.0.1:8090/api/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}

# 3. Systemd para auto-restart
[Service]
ExecStart=/path/to/venv/bin/uvicorn server:app --host 127.0.0.1 --port 8090
Restart=always
```

### Action Server

```bash
# Producción con auto-reload off
action-server start --port 8081 --dir /opt/bnexia_graph/bnexia_actions
```

### Concurrencia

NetworkX en RAM soporta **~100 QPS** sin problemas. Para >500 QPS, considerar:
- Caché Redis para queries frecuentes
- Migrar a Neo4j / graph database

### Seguridad

- **No exponer `:8090` directamente** a internet
- Usar Cloudflare Tunnel, Nginx + API Key (`X-API-Key`)
- Rotar credenciales de Action Server si se expone públicamente

---

## Estructura del Proyecto

```
bnexia_graph/
├── corpus/
│   └── n8n_exports/          # JSONs de workflows n8n
├── graphify-out/
│   ├── graph.json             # Grafo NetworkX serializado (268 nodos, 233 edges)
│   ├── cache/
│   │   └── sha256.json        # Cache incremental
│   └── GRAPH_REPORT.md        # Análisis de god nodes, huérfanos, leaf nodes
├── graphify_n8n_standalone/
│   ├── __main__.py            # CLI: python -m graphify_n8n_standalone
│   └── builder.py             # Parser, builder, categorización y reporte
├── graph_api/
│   └── server.py             # FastAPI con endpoints de diagnóstico
├── bnexia_actions/
│   ├── package.yaml           # Manifest Sema4.ai (v2)
│   ├── conda.yaml            # Entorno Conda (Python 3.12)
│   └── graph_actions.py       # 6 @actions MCP para diagnóstico
├── .gitignore
└── README.md                  # Este archivo
```

---

## Contribuir

### Desarrollo

```bash
# Crear entorno virtual
python -m venv venv
source venv/bin/activate
pip install networkx fastapi uvicorn httpx sema4ai-actions

# Correr tests manuales
python -m graphify_n8n_standalone corpus/n8n_exports/

# Levantar API en dev
cd graph_api && uvicorn server:app --port 8090 --reload

# Action Server en dev
cd bnexia_actions && action-server start --auto-reload --expose
```

### Flujo de trabajo

1. Actualizar corpus con nuevos JSONs de n8n
2. Reconstruir grafo: `python -m graphify_n8n_standalone corpus/n8n_exports/`
3. Recargar API: `curl http://localhost:8090/admin/reload`
4. Consultar endpoints o usar MCP tools desde el agente

### Decisiones de diseño

| Decisión                  | Rationale                                                     |
|---------------------------|---------------------------------------------------------------|
| NetworkX (no Neo4j)       | <300 nodos — RAM es suficiente, latencia sub-100ms            |
| Determinista (0 LLM)      | Coste cero, reproducibilidad total, debugging sencillo         |
| FastAPI (no Flask)        | Async nativo, OpenAPI auto-generado, mejor para MCP           |
| Sema4.ai Action Server    | MCP tools auto-generated, conda aislado, --expose para testing|
| SHA256 incremental     | Rebuilds de 1s en lugar de 30s con 10+ archivos              |

---

## License

MIT
