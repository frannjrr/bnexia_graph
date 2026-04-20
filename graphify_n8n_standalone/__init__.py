# graphify_n8n/__init__.py
"""
Graphify for n8n workflows – standalone, no AI assistant needed.
Deterministic parser + optional LLM semantic inference.
"""
from .builder import build_graph

__version__ = "0.1.0"
__all__ = ["build_graph"]
