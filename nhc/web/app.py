"""Flask application factory for the nhc web server."""

from __future__ import annotations

import asyncio
import logging

from flask import Flask, jsonify, make_response, render_template, request
from flask_sock import Sock

from nhc.web.config import WebConfig
from nhc.web.sessions import SessionManager

logger = logging.getLogger(__name__)


def create_app(
    config: WebConfig | None = None,
    auth_token: str | None = None,
) -> Flask:
    """Create and configure the Flask application."""
    config = config or WebConfig()
    app = Flask(
        __name__,
        static_folder="static",
        template_folder="templates",
    )
    app.config["NHC_CONFIG"] = config

    # Set up file + console logging via shared log_utils
    from nhc.log_utils import setup_logging
    log_path = setup_logging(
        level=logging.DEBUG,
        debug_topics="all",
        console_output=True,
    )
    logger.info("Log file: %s", log_path)

    sessions = SessionManager(config)
    app.config["SESSIONS"] = sessions

    # Auth setup
    valid_hashes: set[str] = set()
    if auth_token:
        from nhc.web.auth import hash_token
        valid_hashes.add(hash_token(auth_token))
    app.config["AUTH_HASHES"] = valid_hashes

    sock = Sock(app)

    # Register WebSocket routes
    from nhc.web.ws import register_ws
    register_ws(app, sock)

    @app.route("/")
    def index():
        if config.auth_required and valid_hashes:
            from nhc.web.auth import hash_token, _extract_token
            token = _extract_token()
            if not token or hash_token(token) not in valid_hashes:
                return "Authentication required. Add ?token=YOUR_TOKEN", 401
            resp = make_response(render_template("index.html"))
            resp.set_cookie("nhc_token", token, httponly=True,
                            samesite="Strict")
            return resp
        return render_template("index.html")

    # Apply auth to API routes if enabled
    def _maybe_auth(f):
        if config.auth_required and valid_hashes:
            from nhc.web.auth import require_auth
            return require_auth(valid_hashes)(f)
        return f

    @app.route("/api/game/new", methods=["POST"])
    @_maybe_auth
    def game_new():
        data = request.get_json(silent=True) or {}
        lang = data.get("lang", "")
        tileset = data.get("tileset", "")
        logger.info("Creating new game: lang=%s tileset=%s reset=%s",
                     lang, tileset, config.reset)
        try:
            session = sessions.create(lang=lang, tileset=tileset)
        except ValueError as exc:
            logger.warning("Session limit: %s", exc)
            return jsonify({"error": str(exc)}), 429

        # Initialize i18n and create the game instance
        from nhc.i18n import init as i18n_init
        i18n_init(session.lang)

        from nhc.core.game import Game
        from nhc.llm import create_backend
        from nhc.rendering.web_client import WebClient

        client = WebClient(game_mode="classic", lang=session.lang)
        backend = create_backend({
            "provider": "ollama",
            "model": config.ollama_model,
            "url": config.ollama_url,
            "temp": 0.1,
            "ctx": 16384,
        })
        logger.debug("LLM backend: %s", type(backend).__name__
                      if backend else "None")

        game = Game(
            client=client,
            backend=backend,
            game_mode="classic",
            reset=config.reset,
        )
        session.game = game

        # Initialize the game world (generate dungeon)
        logger.info("Generating dungeon for session %s...",
                     session.session_id)
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(game.initialize(generate=True))
        except Exception:
            logger.exception("Failed to initialize game")
            sessions.destroy(session.session_id)
            return jsonify({"error": "game initialization failed"}), 500
        finally:
            loop.close()

        logger.info("Dungeon generated: %dx%d, %d rooms",
                     game.level.width, game.level.height,
                     len(game.level.rooms))

        # Generate floor SVG and store on the client
        from nhc.rendering.svg import render_floor_svg
        if game.level:
            logger.info("Rendering floor SVG...")
            client.floor_svg = render_floor_svg(
                game.level, seed=game.seed or 0,
            )
            logger.info("Floor SVG: %d bytes", len(client.floor_svg))
        else:
            logger.warning("No level — floor SVG not generated")

        logger.info("Session %s ready, waiting for WS connection",
                     session.session_id)
        return jsonify({
            "session_id": session.session_id,
            "lang": session.lang,
            "tileset": session.tileset,
        }), 201

    @app.route("/api/game/list", methods=["GET"])
    @_maybe_auth
    def game_list():
        return jsonify(sessions.list_sessions())

    @app.route("/api/game/<session_id>", methods=["DELETE"])
    @_maybe_auth
    def game_delete(session_id: str):
        if sessions.destroy(session_id):
            return jsonify({"status": "ok"})
        return jsonify({"error": "session not found"}), 404

    @app.route("/api/tilesets", methods=["GET"])
    def tilesets():
        return jsonify(["classic"])

    @app.route("/api/help/<lang>", methods=["GET"])
    def help_text(lang: str):
        """Serve the help document for the given language."""
        from pathlib import Path
        docs = Path(__file__).parent.parent.parent / "docs"
        path = docs / f"help_{lang}.md"
        if not path.exists():
            path = docs / "help_en.md"
        if not path.exists():
            return "Help not available.", 404
        return path.read_text(), 200, {"Content-Type": "text/plain"}

    return app
