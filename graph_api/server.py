import json, networkx as nx
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()
G: nx.DiGraph = None

def load_graph():
    global G
    with open("../graphify-out/graph.json") as f:
        data = json.load(f)
    G = nx.node_link_graph(data)
    print(f"✅ Grafo cargado: {G.number_of_nodes()} nodos, {G.number_of_edges()} edges")

@app.on_event("startup")
def startup():
    try: load_graph()
    except: print("⚠️ No se cargó el grafo")

# CAMBIO 1: GET para facilitar pruebas con curl
@app.get("/admin/reload")
def reload():
    try:
        load_graph()
        return {"status": "reloaded", "nodes": G.number_of_nodes()}
    except Exception as e:
        return {"error": str(e)}

class QueryReq(BaseModel):
    query: str
    budget: int = 500

class PathReq(BaseModel):
    source: str
    target: str

# CAMBIO 2: Modelo exclusivo para blast_radius (solo requiere source)
class BlastReq(BaseModel):
    source: str

@app.post("/query")
def query_graph(req: QueryReq):
    hits = [n for n in G.nodes if req.query.lower() in str(n).lower()]
    if not hits: return {"message": "No match found"}
    return {"root": hits[0], "subgraph": _bfs_budget(hits[0], req.budget)}

@app.post("/path")
def shortest_path(req: PathReq):
    try:
        path = nx.shortest_path(G, req.source, req.target)
        return {"path": path, "hops": len(path)-1}
    except nx.NetworkXNoPath:
        return {"error": "No path found"}

@app.get("/neighbors/{node}")
def neighbors(node: str, depth: int = 1):
    nodes = {node}
    for _ in range(depth):
        nodes |= {n for src in nodes for n in G.successors(src)}
        nodes |= {n for tgt in nodes for n in G.predecessors(tgt)}
    return {"neighbors": list(nodes - {node})}

@app.post("/blast_radius")
def blast_radius(req: BlastReq):
    if req.source not in G:
        return {"error": f"Node '{req.source}' not found"}
    try:
        downstream = list(nx.descendants(G, req.source))
        direct_impact = [
            n for n in G.successors(req.source)
            if G[req.source][n].get("source_type") == "EXTRACTED"
        ]
        return {
            "source": req.source,
            "total_impacted": len(downstream),
            "blast_radius": downstream,
            "direct_impact": direct_impact
        }
    except Exception as e:
        return {"error": str(e)}

def _bfs_budget(root, budget):
    visited, queue, tokens = [], [root], 0
    while queue and tokens < budget:
        node = queue.pop(0)
        if node in visited: continue
        data = G.nodes[node]
        visited.append({"node": node, "data": data})
        tokens += len(str(data)) // 4
        queue.extend(G.successors(node))
    return visited
class DiagnosticReq(BaseModel):
    node: str

@app.post("/diagnostic_context")
def diagnostic_context(req: DiagnosticReq):
    target = req.node
    # Fuzzy fallback robusto
    if target not in G:
        hits = [n for n in G.nodes if req.node.lower() in str(n).lower()]
        if hits: target = hits[0]
        else: return {"error": f"Node '{req.node}' no encontrado. Prueba con nombre más específico."}
        
    return {
        "target_node": target,
        "category": G.nodes[target].get("category", "unknown"),
        "upstream": list(G.predecessors(target)),
        "downstream": list(G.successors(target)),
        "blast_radius": list(nx.descendants(G, target)),
        "confidence": G.nodes[target].get("confidence", 1.0)
    }

@app.post("/blast_radius")
def blast_radius(req: PathReq): # Mantengo PathReq para compatibilidad, pero uso solo .source
    src = req.source
    if src not in G:
        # Fuzzy
        hits = [n for n in G.nodes if src.lower() in str(n).lower()]
        if hits: src = hits[0]
        else: return {"error": f"Node '{src}' not found"}
        
    all_successors = list(G.successors(src))
    extracted_successors = [n for n in all_successors if G[src][n].get("source_type") == "EXTRACTED"]
    
    return {
        "source": src,
        "total_impacted": len(list(nx.descendants(G, src))),
        "blast_radius": list(nx.descendants(G, src)),
        "direct_impact": extracted_successors if extracted_successors else all_successors
    }
