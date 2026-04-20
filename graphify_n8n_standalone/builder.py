# graphify_n8n/builder.py
"""
Core graph builder for n8n JSON exports.
Produces graph.json and GRAPH_REPORT.md compatible with bnexia_graph API.
"""
import json
import hashlib
import os
from pathlib import Path
from collections import defaultdict
from typing import Any

import networkx as nx


def _file_hash(filepath: str) -> str:
    """SHA256 of file content for incremental cache."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_cache(cache_dir: str) -> dict[str, str]:
    cache_file = os.path.join(cache_dir, "sha256.json")
    if os.path.exists(cache_file):
        with open(cache_file) as f:
            return json.load(f)
    return {}


def _save_cache(cache_dir: str, hashes: dict[str, str]):
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = os.path.join(cache_dir, "sha256.json")
    with open(cache_file, "w") as f:
        json.dump(hashes, f, indent=2)


def _parse_n8n_workflow(filepath: str) -> dict[str, Any]:
    """Parse a single n8n JSON export into nodes and edges."""
    with open(filepath) as f:
        raw = json.load(f)

    # Normalizar a formato workflow
    workflows = raw if isinstance(raw, list) else [raw]
    nodes = []
    edges = []
    metadata = {}

    for wf in workflows:
        wf_name = wf.get("name", Path(filepath).stem)
        metadata["workflow_name"] = wf_name
        metadata["version"] = wf.get("versionId", "unknown")

        for node in wf.get("nodes", []):
            node_id = node.get("id", node.get("name"))
            node_type = node.get("type", "unknown")
            node_name = node.get("name", node_id)

            nodes.append({
                "node": node_name,
                "type": node_type,
                "workflow": wf_name,
                "label": f"{wf_name} → {node_name}",
                "category": _categorize_node(node_type),
                "source": "EXTRACTED",
                "confidence": 1.0,
                "file": filepath,
            })

        for source, connections in wf.get("connections", {}).items():
            for output_type, output_list in connections.items():
                for output_idx, targets in enumerate(output_list):
                    if targets is None:
                        continue
                    for target in targets:
                        target_name = target.get("node")
                        if target_name:
                            edges.append({
                                "source": source,
                                "target": target_name,
                                "workflow": wf_name,
                                "connection_type": output_type,
                                "output_index": output_idx,
                                "source_type": "EXTRACTED",
                                "confidence": 1.0,
                            })

    return {"nodes": nodes, "edges": edges, "metadata": metadata, "filepath": filepath}


def _categorize_node(node_type: str) -> str:
    """Categorize n8n node types into semantic buckets."""
    t = node_type.lower()
    if any(k in t for k in ["webhook", "trigger", "cron", "interval"]):
        return "trigger"
    if any(k in t for k in ["http", "request", "api", "graphql"]):
        return "api_call"
    if any(k in t for k in ["agent", "llm", "chat", "model", "openai", "anthropic"]):
        return "ai_agent"
    if any(k in t for k in ["set", "code", "function", "transform"]):
        return "transform"
    if any(k in t for k in ["if", "switch", "merge", "route"]):
        return "conditional"
    if any(k in t for k in ["database", "postgres", "mysql", "mongo"]):
        return "data_store"
    if any(k in t for k in ["slack", "email", "discord", "telegram", "sms"]):
        return "notification"
    if any(k in t for k in ["sheet", "spreadsheet", "excel", "csv"]):
        return "data_processing"
    return "generic"


def _merge_graphs(parsed_workflows: list[dict]) -> nx.DiGraph:
    """Merge multiple parsed workflows into a single NetworkX graph."""
    G = nx.DiGraph()
    workflow_nodes = defaultdict(set)
    shared_credentials = defaultdict(list)

    for wf in parsed_workflows:
        for node in wf["nodes"]:
            node_label = node["label"]
            node_data = {k: v for k, v in node.items() if k not in ("node", "label")}
            G.add_node(node_label, **node_data)
            workflow_nodes[wf["metadata"]["workflow_name"]].add(node_label)

        for edge in wf["edges"]:
            src_label = f"{edge['workflow']} → {edge['source']}"
            tgt_label = f"{edge['workflow']} → {edge['target']}"
            edge_data = {k: v for k, v in edge.items() if k not in ("source", "target")}
            if G.has_edge(src_label, tgt_label):
                continue
            G.add_edge(src_label, tgt_label, **edge_data)

    # Detectar relaciones entre workflows (mismo tipo de trigger, mismo patrón de nodos)
    _add_cross_workflow_edges(G, workflow_nodes)

    return G


def _add_cross_workflow_edges(G: nx.DiGraph, workflow_nodes: dict[str, set[str]]):
    """Infer edges between workflows that share node types or patterns."""
    wf_types = defaultdict(set)
    for wf_name, nodes in workflow_nodes.items():
        for node_label in nodes:
            if G.has_node(node_label):
                cat = G.nodes[node_label].get("category", "generic")
                wf_types[wf_name].add(cat)

    for wf_a, types_a in wf_types.items():
        for wf_b, types_b in wf_types.items():
            if wf_a >= wf_b:
                continue
            shared = types_a & types_b
            if shared:
                # Conectar los triggers de ambos workflows
                triggers_a = [n for n in workflow_nodes[wf_a]
                              if G.nodes[n].get("category") == "trigger"]
                triggers_b = [n for n in workflow_nodes[wf_b]
                              if G.nodes[n].get("category") == "trigger"]
                if triggers_a and triggers_b:
                    G.add_edge(
                        triggers_a[0], triggers_b[0],
                        type="SIMILAR_PATTERN",
                        source="INFERRED",
                        confidence=0.6,
                        reasoning=f"Both workflows use: {', '.join(shared)}",
                    )


def _generate_report(G: nx.DiGraph, output_dir: str):
    """Generate GRAPH_REPORT.md with analysis."""
    report_path = os.path.join(output_dir, "GRAPH_REPORT.md")

    # Centrality
    in_degree = dict(G.in_degree())
    out_degree = dict(G.out_degree())

    god_nodes = sorted(G.nodes(), key=lambda n: in_degree.get(n, 0), reverse=True)[:15]
    orphans = [n for n in G.nodes() if in_degree.get(n, 0) == 0 and out_degree.get(n, 0) == 0]
    leaf_nodes = [n for n in G.nodes() if out_degree.get(n, 0) == 0]

    # Confianza por tipo
    extracted_edges = sum(1 for _, _, d in G.edges(data=True) if d.get("source") == "EXTRACTED")
    inferred_edges = sum(1 for _, _, d in G.edges(data=True) if d.get("source") == "INFERRED")

    lines = [
        "# Graph Analysis Report",
        "",
        f"- **Nodes:** {G.number_of_nodes()}",
        f"- **Edges:** {G.number_of_edges()}",
        f"- **EXTRACTED edges:** {extracted_edges} (deterministas)",
        f"- **INFERRED edges:** {inferred_edges} (semánticas)",
        "",
        "## 🔱 God Nodes (más conectadas)",
        "",
    ]
    for node in god_nodes:
        lines.append(f"- `{node}` → in:{in_degree.get(node, 0)} out:{out_degree.get(node, 0)}")

    lines += [
        "",
        "## 🕳️ Huérfanos (sin connections)",
        "",
    ]
    if orphans:
        for node in orphans[:10]:
            lines.append(f"- `{node}`")
    else:
        lines.append("- Ninguno detectado.")

    lines += [
        "",
        "## 🍃 Leaf Nodes (terminales)",
        "",
    ]
    for node in leaf_nodes[:15]:
        lines.append(f"- `{node}`")

    lines += [
        "",
        "## 💡 Recomendaciones",
        "",
        "- Revisá las edges INFERRED con confidence < 0.7",
        "- Los huérfanos pueden indicar archivos mal parseados",
        "- Los god nodes son conceptos clave de tu infraestructura",
    ]

    with open(report_path, "w") as f:
        f.write("\n".join(lines))


def build_graph(corpus_dir: str, output_dir: str = "graphify-out", incremental: bool = False):
    """
    Build knowledge graph from n8n JSON exports.
    Args:
        corpus_dir: Path to directory containing n8n JSON files
        output_dir: Path to output directory (default: graphify-out)
        incremental: Only process changed files (uses SHA256 cache)
    """
    os.makedirs(output_dir, exist_ok=True)
    cache_dir = os.path.join(output_dir, "cache")
    os.makedirs(cache_dir, exist_ok=True)

    # Detectar archivos JSON
    json_files = list(Path(corpus_dir).rglob("*.json"))
    if not json_files:
        raise FileNotFoundError(f"No JSON files found in {corpus_dir}")

    # Cache incremental
    cache = _load_cache(cache_dir) if incremental else {}
    new_hashes = {}
    parsed = []
    changed = 0

    for fpath in json_files:
        h = _file_hash(str(fpath))
        new_hashes[str(fpath)] = h
        if incremental and cache.get(str(fpath)) == h:
            continue  # Sin cambios
        changed += 1
        parsed.append(_parse_n8n_workflow(str(fpath)))

    _save_cache(cache_dir, new_hashes)
    print(f"📊 Procesados {changed}/{len(json_files)} archivos (cambiaron desde última vez)")

    if not parsed:
        print("⚠️ No hay archivos nuevos o modificados. El grafo no cambió.")
        # Cargar último grafo si existe
        graph_path = os.path.join(output_dir, "graph.json")
        if os.path.exists(graph_path):
            print(f"✅ Grafo existente en {graph_path}")
            return

    # Construir grafo
    G = _merge_graphs(parsed)
    print(f"🧠 Grafo: {G.number_of_nodes()} nodos, {G.number_of_edges()} edges")

    # Guardar
    graph_path = os.path.join(output_dir, "graph.json")
    data = nx.node_link_data(G)
    with open(graph_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"💾 Guardado en {graph_path}")

    # Generar reporte
    _generate_report(G, output_dir)
    print(f"📄 Reporte en {os.path.join(output_dir, 'GRAPH_REPORT.md')}")

    return G
