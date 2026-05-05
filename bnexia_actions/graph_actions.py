import json
import os
import sys
import subprocess
import httpx
from pathlib import Path
from sema4ai.actions import action

# Rutas base del proyecto
PROJECT_ROOT = Path(__file__).parent.parent
GRAPH_API_URL = os.environ.get("GRAPH_API_URL", "http://127.0.0.1:8090")
CORPUS_DEFAULT = str(PROJECT_ROOT / "corpus" / "n8n_exports")
OUTPUT_DEFAULT = str(PROJECT_ROOT / "graphify-out")

# Inyectar graphify_n8n_standalone al path si no está
graphify_path = str(PROJECT_ROOT / "graphify_n8n_standalone")
if graphify_path not in sys.path:
    sys.path.insert(0, graphify_path)


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


def _run_graphify(corpus_path: str, output_dir: str, incremental: bool) -> dict:
    """Ejecuta el builder de graphify como subprocess y captura output."""
    try:
        cmd = [
            sys.executable, "-m", "graphify_n8n_standalone",
            corpus_path,
            "--output", output_dir,
        ]
        if incremental:
            cmd.append("--update")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(PROJECT_ROOT)
        )

        output_lines = result.stdout.strip().split("\n") if result.stdout else []

        # Parsear métricas del output
        nodes = edges = 0
        for line in output_lines:
            if "Grafo:" in line:
                # "🧠 Grafo: 268 nodos, 233 edges"
                parts = line.split(":")[1]
                nodes_part = parts.split("nodos")[0].strip()
                edges_part = parts.split("edges")[0].strip().split(",")[1].strip()
                try:
                    nodes = int(nodes_part)
                    edges = int(edges_part)
                except (ValueError, IndexError):
                    pass

        return {
            "status": "success" if result.returncode == 0 else "error",
            "nodes": nodes,
            "edges": edges,
            "graph_file": os.path.join(output_dir, "graph.json"),
            "report": os.path.join(output_dir, "GRAPH_REPORT.md"),
            "output": output_lines,
            "stderr": result.stderr.strip() if result.stderr else None
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Timeout: graphify tardó más de 120s"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action
async def get_diagnostic_context(node: str) -> str:
    """Obtiene el contexto completo de diagnóstico para un nodo de n8n.
    Usa esto cuando un workflow falle o necesites entender las dependencias de un componente.
    Soporta búsqueda parcial (fuzzy matching).

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
    Úsalo para evaluar riesgo antes de cambios o al diagnosticar fallos en triggers críticos.

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
    Útil para entender cómo se conectan componentes distantes o por qué un error tarda en propagarse.

    Args:
        source: Nodo de origen.
        target: Nodo de destino.

    Returns:
        JSON string con: path (lista), hops. Si no hay ruta: {"error": "No path found"}.
    """
    result = await _call_graph_api("path", {"source": source, "target": target})
    return json.dumps(result, ensure_ascii=False, indent=2)


@action
def graphify_build(
    corpus_path: str = "",
    output_dir: str = "",
    incremental: bool = False
) -> str:
    """Construye el grafo operativo desde archivos JSON de n8n (o cualquier fuente compatible).
    
    Esta es la herramienta principal para generar/actualizar el grafo de conocimiento.
    El grafo resultante se expone automáticamente vía graph_api (:8090) y MCP tools.
    
    El parser es 100% determinista (0 llamadas a LLM), extrae nodos, conexiones reales
    y patrones cruzados entre workflows.
    
    Args:
        corpus_path: Ruta absoluta a la carpeta con archivos JSON. 
                     Por defecto: corpus/n8n_exports/ del proyecto.
        output_dir: Directorio de salida para graph.json y reportes.
                    Por defecto: graphify-out/ del proyecto.
        incremental: Si es True, solo procesa archivos modificados desde la última build.
                     Usa caché SHA256 para detección de cambios.
    
    Returns:
        JSON string con: status, nodes, edges, graph_file, report, output.
    
    Examples:
        >>> result = graphify_build()  # Build completo por defecto
        >>> result = graphify_build("/home/user/corpus/", incremental=True)
    """
    # Resolver paths por defecto
    corpus = corpus_path if corpus_path else CORPUS_DEFAULT
    output = output_dir if output_dir else OUTPUT_DEFAULT
    
    # Validar que el corpus existe
    if not os.path.isdir(corpus):
        return json.dumps({
            "status": "error",
            "message": f"Corpus no encontrado: {corpus}. Asegúrate de que la carpeta existe y contiene JSONs de n8n."
        }, ensure_ascii=False, indent=2)
    
    # Ejecutar graphify
    build_result = _run_graphify(corpus, output, incremental)
    
    # Recargar grafo en API si la build fue exitosa
    if build_result["status"] == "success" and build_result.get("nodes", 0) > 0:
        try:
            import urllib.request
            reload_url = f"{GRAPH_API_URL}/admin/reload"
            urllib.request.urlopen(reload_url, timeout=5)
            build_result["api_reloaded"] = True
        except Exception:
            build_result["api_reloaded"] = False
            build_result["api_note"] = "La API no estaba corriendo. Levanta graph_api y llama a /admin/reload manualmente."
    
    return json.dumps(build_result, ensure_ascii=False, indent=2)


@action
def start_graph_api(port: int = 8090) -> str:
    """Levanta la API FastAPI de graph_api en el puerto especificado.
    
    La API expone endpoints de diagnóstico, blast_radius y rutas causales.
    Es necesaria para que las MCP tools (get_diagnostic_context, etc.) funcionen.
    
    Args:
        port: Puerto donde escuchar. Por defecto 8090.
    
    Returns:
        JSON string con: status, message, kill_command.
    
    Notes:
        Esta acción inicia uvicorn en background. Para producción, usar systemd o supervisor.
    """
    server_path = str(PROJECT_ROOT / "graph_api" / "server.py")
    
    if not os.path.exists(server_path):
        return json.dumps({
            "status": "error",
            "message": f"server.py no encontrado en {server_path}"
        }, ensure_ascii=False, indent=2)
    
    try:
        # Verificar si el puerto ya está en uso
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('127.0.0.1', port))
        sock.close()
        
        if result == 0:
            return json.dumps({
                "status": "already_running",
                "message": f"graph_api ya está corriendo en el puerto {port}",
                "test_url": f"http://127.0.0.1:{port}/admin/reload"
            }, ensure_ascii=False, indent=2)
        
        # Iniciar uvicorn en background
        cmd = f"cd {PROJECT_ROOT}/graph_api && nohup uvicorn server:app --host 0.0.0.0 --port {port} > /tmp/graph_api.log 2>&1 &"
        os.system(cmd)
        
        return json.dumps({
            "status": "started",
            "message": f"graph_api iniciando en puerto {port}",
            "log_file": "/tmp/graph_api.log",
            "test_url": f"http://127.0.0.1:{port}/admin/reload",
            "kill_command": f"kill $(lsof -t -i:{port})"
        }, ensure_ascii=False, indent=2)
        
    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": str(e)
        }, ensure_ascii=False, indent=2)


@action
def graphify_full_pipeline(
    corpus_path: str = "",
    port: int = 8090,
    incremental: bool = False
) -> str:
    """Orquesta el flujo completo: levanta la API + construye el grafo + recarga.
    
    Esta es la acción 'one-shot' para tener todo funcionando desde cero.
    Ideal para usar en chat con OWUI: el agente ejecuta esto y ya puede consultar el grafo.
    
    Args:
        corpus_path: Ruta a archivos JSON de n8n.
        port: Puerto para graph_api.
        incremental: Solo procesar archivos modificados.
    
    Returns:
        JSON string con: api_status, graph_status, nodes, edges, ready.
    """
    pipeline = {}
    
    # Paso 1: Levantar API
    pipeline["step_1_api"] = json.loads(start_graph_api(port))
    
    # Esperar a que la API arranque
    import time
    time.sleep(2)
    
    # Paso 2: Construir grafo
    pipeline["step_2_graphify"] = json.loads(graphify_build(corpus_path, "", incremental))
    
    # Resultado consolidado
    return json.dumps({
        "status": "complete",
        "api": pipeline.get("step_1_api", {}),
        "graph": pipeline.get("step_2_graphify", {}),
        "ready": True
    }, ensure_ascii=False, indent=2)
