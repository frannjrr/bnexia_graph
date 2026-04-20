# graphify_n8n/__main__.py
"""CLI entry point: python -m graphify_n8n corpus/n8n_exports/"""
import argparse
import sys
from .builder import build_graph


def main():
    parser = argparse.ArgumentParser(description="Build knowledge graph from n8n workflows")
    parser.add_argument("corpus", help="Path to corpus directory (n8n JSONs)")
    parser.add_argument("--output", default="graphify-out", help="Output directory")
    parser.add_argument("--update", action="store_true", help="Incremental rebuild")
    args = parser.parse_args()

    try:
        build_graph(args.corpus, args.output, incremental=args.update)
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
