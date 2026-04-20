# 📊 `bnexia_graph`: Infraestructura Operativa como Grafo
> Transforma exportaciones JSON de n8n en un grafo dirigido, queryable y de latencia <100ms para diagnóstico causal y exposición MCP.

![Python](https://img.shields.io/badge/Python-3.11+-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.105-009688)
![NetworkX](https://img.shields.io/badge/NetworkX-3.1-orange)
![Sema4AI](https://img.shields.io/badge/Action_Server-MCP-purple)
![Latency](https://img.shields.io/badge/Query_Latency-<100ms-brightgreen)

---

### 🧠 Concepto
Los flujos de automatización modernos (n8n, LangChain) generan complejidad lineal difícil de auditar. `bnexia_graph` rompe con el enfoque tradicional de **Búsqueda RAG** (probabilística) para implementar un enfoque de **Graph Engineering** (determinista).

En lugar de buscar "textos similares" que hablen de un error, este sistema **navega la topología real** de tu infraestructura para responder:
> *"Si falla el Webhook A, ¿qué nodos exactos se rompen y en qué orden?"*

### 🏗️ Arquitectura
El sistema opera en tres capas desacopladas:

1.  **Ingesta (`graphify`):** Parser determinista (0 LLM calls) que extrae nodos y conexiones de JSONs crudos.
2.  **Motor (`NetworkX`):** Grafo en memoria RAM. Búsquedas BFS/Dijkstra ultra-rápidas.
3.  **Exposición (`Action Server`):** Wrapper MCP que expone el grafo como herramientas para Agentes IA (LangChain, OpenWebUI).

```mermaid
graph LR
    A[Raw JSON Exports] -->|Parser Determinista| B(Grafo NetworkX 268 Nodos)
    B -->|Queries BFS/Path| C[FastAPI :8090]
    C -->|HTTP/JSON| D[Sema4 Action Server]
    D -->|MCP/Tools| E[LLM Agentes]
    
    style B fill:#f9f,stroke:#333,stroke-width:2px
    style C fill:#bbf,stroke:#333,stroke-width:2px
    style D fill:#bfb,stroke:#333,stroke-width:2px
