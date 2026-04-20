import json
import httpx
from sema4ai.actions import action

# Apunta a tu API gráfica local (capa 2 de bnexia_graph) [2]
GRAPH_API_URL = "http://127.0.0.1:8090"

async def _call_graph_api(endpoint: str, payload: dict) -> dict:
    """Helper para llamar a graph_api y devolver JSON estructurado o error."""
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(f"{GRAPH_API_URL}/{endpoint}", json=payload, timeout=10)
            res.raise_for_status()
            return res.json()
    except httpx.RequestError as e:
        return {"error": f"Error de conexión a graph_api: {str(e)}"}
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}

@action
async def get_diagnostic_context(node: str) -> str:
    """Obtiene el contexto completo de diagnóstico para un nodo de n8n.
    Usa esto cuando un workflow falle o necesites entender las dependencias de un componente.
    Soporta búsqueda parcial (fuzzy matching) [2].

    Args:
        node: Nombre del nodo o workflow (ej: 'MCP B-CONNECT', 'docx gen', 'Bearer').

    Returns:
        JSON string con: target_node, category, upstream, downstream, blast_radius, confidence.
    """
    result = await _call_graph_api("diagnostic_context", {"node": node})
    return json.dumps(result, ensure_ascii=False, indent=2)

@action
async def calculate_blast_radius(source_node: str) -> str:
    """Calcula el impacto cascada si falla o se modifica un nodo específico.
    Úsalo para evaluar riesgo antes de cambios o al diagnosticar fallos en triggers críticos [2].

    Args:
        source_node: Nombre exacto o parcial del nodo origen del impacto.

    Returns:
        JSON string con: source, total_impacted, blast_radius, direct_impact.
    """
    result = await _call_graph_api("blast_radius", {"source": source_node})
    return json.dumps(result, ensure_ascii=False, indent=2)

@action
async def find_causal_path(source: str, target: str) -> str:
    """Encuentra la ruta causal más corta entre dos nodos en el grafo de n8n.
    Útil para entender cómo se conectan componentes distantes o por qué un error tarda en propagarse [2].

    Args:
        source: Nodo de origen.
        target: Nodo de destino.

    Returns:
        JSON string con: path (lista), hops. Si no hay ruta: {"error": "No path found"}.
    """
    result = await _call_graph_api("path", {"source": source, "target": target})
    return json.dumps(result, ensure_ascii=False, indent=2)
