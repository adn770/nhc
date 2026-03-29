"""Flask application factory for the nhc web server."""

from __future__ import annotations

from flask import Flask, jsonify, request

from nhc.web.config import WebConfig
from nhc.web.sessions import SessionManager


def create_app(config: WebConfig | None = None) -> Flask:
    """Create and configure the Flask application."""
    config = config or WebConfig()
    app = Flask(__name__)
    app.config["NHC_CONFIG"] = config

    sessions = SessionManager(config)
    app.config["SESSIONS"] = sessions

    @app.route("/api/game/new", methods=["POST"])
    def game_new():
        data = request.get_json(silent=True) or {}
        lang = data.get("lang", "")
        tileset = data.get("tileset", "")
        try:
            session = sessions.create(lang=lang, tileset=tileset)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 429
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
