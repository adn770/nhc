#!/usr/bin/env python3
"""NHC Web Server — entry point.

Serves the nhc web frontend with multiple concurrent game sessions.

Usage:
  python nhc_web.py                          # Local dev, no auth
  python nhc_web.py --auth                   # Generate token and require auth
  python nhc_web.py --host 0.0.0.0 --auth    # Exposed on network with auth
"""

import argparse
import os
from pathlib import Path

from nhc.hexcrawl.mode import add_mode_args
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
        "--port", type=int, default=5005,
        help="Port (default: 5005)",
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
    parser.add_argument(
        "--auth", action="store_true",
        help="Enable token authentication (generates and prints a token)",
    )
    parser.add_argument(
        "--token",
        help="Use a specific auth token instead of generating one",
    )
    parser.add_argument(
        "--reset", action="store_true",
        help="Start a new game, ignoring any autosave",
    )
    parser.add_argument(
        "--shape-variety", type=float, default=0.3,
        help="Room shape variety 0.0-1.0 (default: 0.3, scales with depth)",
    )
    parser.add_argument(
        "--god", action="store_true",
        help="God mode: invulnerable, debug tools enabled",
    )
    parser.add_argument(
        "--data-dir",
        help="Persistent data directory (env: NHC_DATA_DIR)",
    )
    # Local dev server launches on the hexcrawl overland by
    # default so `./server` drops the player onto the hex map
    # without explicit CLI overrides. Dungeon-only play still
    # works via `./server --world dungeon`.
    add_mode_args(
        parser, default_world="hexcrawl", default_difficulty="medium",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    auth_token = None
    if args.auth or args.token:
        if args.token:
            auth_token = args.token
        else:
            from nhc.web.auth import generate_token
            auth_token = generate_token()

    data_dir_str = args.data_dir or os.environ.get("NHC_DATA_DIR")
    data_dir = Path(data_dir_str) if data_dir_str else None

    config = WebConfig(
        host=args.host,
        port=args.port,
        max_sessions=args.max_sessions,
        ollama_url=args.ollama_url,
        ollama_model=args.ollama_model,
        auth_required=auth_token is not None,
        reset=args.reset,
        shape_variety=args.shape_variety,
        god_mode=args.god,
        data_dir=data_dir,
    )
    app = create_app(config, auth_token=auth_token)

    url = f"http://{config.host}:{config.port}"
    print(f"NHC web server starting on {url}")
    if auth_token:
        print(f"Auth token: {auth_token}")
        print(f"Access URL: {url}?token={auth_token}")

    print("(dev mode — for production use: gunicorn --worker-class "
          "gthread -w1 --threads 32 -b 0.0.0.0:8080 "
          "'nhc.web.app:app_factory()')")
    app.run(host=config.host, port=config.port, debug=True)


if __name__ == "__main__":
    main()
