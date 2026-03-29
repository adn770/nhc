"""Flask application factory for the nhc web server."""

from __future__ import annotations

import asyncio

from flask import Flask, jsonify, render_template, request
from flask_sock import Sock

from nhc.web.config import WebConfig
from nhc.web.sessions import SessionManager


def create_app(config: WebConfig | None = None) -> Flask:
    """Create and configure the Flask application."""
    config = config or WebConfig()
    app = Flask(
        __name__,
        static_folder="static",
        template_folder="templates",
    )
    app.config["NHC_CONFIG"] = config

    sessions = SessionManager(config)
    app.config["SESSIONS"] = sessions

    sock = Sock(app)

    # Register WebSocket routes
    from nhc.web.ws import register_ws
    register_ws(app, sock)

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/game/new", methods=["POST"])
    def game_new():
        data = request.get_json(silent=True) or {}
        lang = data.get("lang", "")
        tileset = data.get("tileset", "")
        try:
            session = sessions.create(lang=lang, tileset=tileset)
        except ValueError as exc:
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
        game = Game(
            client=client,
            backend=backend,
            game_mode="classic",
        )
        session.game = game

        # Initialize the game world (generate dungeon)
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(game.initialize(generate=True))
        finally:
            loop.close()

        # Generate floor SVG and store on the client
        from nhc.rendering.svg import render_floor_svg
        if game.level:
            client.floor_svg = render_floor_svg(
                game.level, seed=game.seed or 0,
            )

        return jsonify({
            "session_id": session.session_id,
            "lang": session.lang,
            "tileset": session.tileset,
        }), 201

    @app.route("/api/game/list", methods=["GET"])
    def game_list():
        return jsonify(sessions.list_sessions())

    @app.route("/api/game/<session_id>", methods=["DELETE"])
    def game_delete(session_id: str):
        if sessions.destroy(session_id):
            return jsonify({"status": "ok"})
        return jsonify({"error": "session not found"}), 404

    @app.route("/api/tilesets", methods=["GET"])
    def tilesets():
        return jsonify(["classic"])

    return app
