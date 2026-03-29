#!/usr/bin/env python3
"""NHC Web Server — entry point.

Serves the nhc web frontend with multiple concurrent game sessions.
"""

import argparse

from nhc.web.app import create_app
from nhc.web.config import WebConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="NHC web server — roguelike in your browser",
    )
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="Bind address (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port", type=int, default=5000,
        help="Port (default: 5000)",
    )
    parser.add_argument(
        "--max-sessions", type=int, default=8,
        help="Max concurrent game sessions (default: 8)",
    )
    parser.add_argument(
        "--ollama-url", default="http://localhost:11434",
        help="Ollama API URL for LLM inference",
    )
    parser.add_argument(
        "--ollama-model", default="gemma3:12b",
        help="Default ollama model (default: gemma3:12b)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = WebConfig(
        host=args.host,
        port=args.port,
        max_sessions=args.max_sessions,
        ollama_url=args.ollama_url,
        ollama_model=args.ollama_model,
    )
    app = create_app(config)
    print(f"NHC web server starting on http://{config.host}:{config.port}")
    try:
        from waitress import serve
        serve(app, host=config.host, port=config.port)
    except ImportError:
        print("(waitress not installed, using Flask dev server)")
        app.run(host=config.host, port=config.port, debug=True)


if __name__ == "__main__":
    main()
