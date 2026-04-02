"""Flask application factory for the nhc web server."""

from __future__ import annotations

import asyncio
import collections
import logging
import time

from flask import Flask, jsonify, make_response, render_template, request
from flask_sock import Sock

from nhc.web.config import WebConfig
from nhc.web.sessions import SessionManager, player_id_from_token

logger = logging.getLogger(__name__)


class _RateLimiter:
    """Simple in-memory rate limiter per IP address."""

    def __init__(self, max_requests: int = 5, window: int = 60) -> None:
        self._max = max_requests
        self._window = window
        self._hits: dict[str, collections.deque] = {}

    def is_allowed(self, ip: str) -> bool:
        now = time.monotonic()
        hits = self._hits.setdefault(ip, collections.deque())
        while hits and hits[0] < now - self._window:
            hits.popleft()
        if len(hits) >= self._max:
            return False
        hits.append(now)
        return True


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
    from nhc.utils.log import setup_logging
    log_path = setup_logging(
        level=logging.DEBUG,
        debug_topics="all",
        console_output=True,
    )
    logger.info("Log file: %s", log_path)

    sessions = SessionManager(config)
    app.config["SESSIONS"] = sessions

    _limiter = _RateLimiter(max_requests=5, window=60)

    def _check_rate_limit():
        ip = request.remote_addr or "unknown"
        if not _limiter.is_allowed(ip):
            return jsonify({"error": "rate limit exceeded"}), 429
        return None

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

    def _player_save_dir(pid: str) -> "Path | None":
        """Return the save directory for a player, or None."""
        if not config.data_dir:
            return None
        from pathlib import Path
        return config.data_dir / "players" / pid

    @app.route("/api/player/register", methods=["POST"])
    @_maybe_auth
    def player_register():
        blocked = _check_rate_limit()
        if blocked:
            return blocked
        import secrets as _secrets
        token = _secrets.token_urlsafe(32)
        pid = player_id_from_token(token)
        save_dir = _player_save_dir(pid)
        if save_dir:
            save_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Player registered: %s", pid)
        return jsonify({
            "player_token": token,
            "player_id": pid,
        }), 201

    @app.route("/api/player/login", methods=["POST"])
    @_maybe_auth
    def player_login():
        data = request.get_json(silent=True) or {}
        token = data.get("player_token", "")
        if not token:
            return jsonify({"error": "player_token required"}), 400
        pid = player_id_from_token(token)
        save_dir = _player_save_dir(pid)
        from nhc.core.autosave import has_autosave
        has_save = has_autosave(save_dir) if save_dir else has_autosave()
        existing = sessions.get_by_player(pid)
        return jsonify({
            "player_id": pid,
            "has_save": has_save,
            "active_session": existing.session_id if existing else None,
        })

    @app.route("/api/game/resume", methods=["POST"])
    @_maybe_auth
    def game_resume():
        data = request.get_json(silent=True) or {}
        token = data.get("player_token", "")
        if not token:
            return jsonify({"error": "player_token required"}), 400

        pid = player_id_from_token(token)
        save_dir = _player_save_dir(pid)

        # Check for an active (disconnected) session
        existing = sessions.get_by_player(pid)
        if existing and existing.game and existing.game.level:
            logger.info("Resume: found active session %s for player %s",
                        existing.session_id, pid)
            return jsonify({
                "session_id": existing.session_id,
                "resumed": True,
                "turn": existing.game.turn,
            })

        # No active session — check for autosave on disk
        from nhc.core.autosave import has_autosave
        if not has_autosave(save_dir):
            return jsonify({"has_save": False})

        # Create a new session and restore from autosave
        lang = data.get("lang", "")
        tileset = data.get("tileset", "")
        try:
            session = sessions.create(
                lang=lang, tileset=tileset,
                player_id=pid, save_dir=save_dir,
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 429

        from nhc.i18n import init as i18n_init
        i18n_init(session.lang)

        from nhc.core.game import Game
        from nhc.utils.llm import create_backend
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
            shape_variety=config.shape_variety,
            god_mode=config.god_mode,
            save_dir=save_dir,
        )
        session.game = game

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(game.initialize(generate=True))
        except Exception:
            logger.exception("Failed to restore game for player %s", pid)
            sessions.destroy(session.session_id)
            return jsonify({"error": "game restore failed"}), 500
        finally:
            loop.close()

        # Re-render floor SVG for restored level
        from nhc.rendering.svg import render_floor_svg, render_hatch_svg
        if game.level:
            seed = game.seed or 0
            client.floor_svg = render_floor_svg(game.level, seed=seed)
            client.hatch_svg = render_hatch_svg(seed=seed)

        logger.info("Resume: restored session %s for player %s (turn=%d)",
                     session.session_id, pid, game.turn)
        return jsonify({
            "session_id": session.session_id,
            "resumed": True,
            "turn": game.turn,
        }), 201

    @app.route("/api/game/has_save", methods=["GET"])
    @_maybe_auth
    def game_has_save():
        from nhc.core.autosave import has_autosave
        token = request.args.get("player_token", "")
        if token:
            pid = player_id_from_token(token)
            save_dir = _player_save_dir(pid)
            return jsonify({"has_save": has_autosave(save_dir)})
        return jsonify({"has_save": has_autosave()})

    @app.route("/api/game/new", methods=["POST"])
    @_maybe_auth
    def game_new():
        blocked = _check_rate_limit()
        if blocked:
            return blocked
        data = request.get_json(silent=True) or {}
        lang = data.get("lang", "")
        tileset = data.get("tileset", "")
        reset = data.get("reset", False) or config.reset
        player_token = data.get("player_token", "")
        pid = ""
        save_dir = None
        if player_token:
            pid = player_id_from_token(player_token)
            save_dir = _player_save_dir(pid)
            if save_dir:
                save_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Creating new game: lang=%s tileset=%s reset=%s "
                     "player=%s", lang, tileset, reset, pid or "anonymous")
        try:
            session = sessions.create(
                lang=lang, tileset=tileset,
                player_id=pid, save_dir=save_dir,
            )
        except ValueError as exc:
            logger.warning("Session limit: %s", exc)
            return jsonify({"error": str(exc)}), 429

        # Initialize i18n and create the game instance
        from nhc.i18n import init as i18n_init
        i18n_init(session.lang)

        from nhc.core.game import Game
        from nhc.utils.llm import create_backend
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
            reset=reset,
            shape_variety=config.shape_variety,
            god_mode=config.god_mode,
            save_dir=session.save_dir,
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

        # Generate floor SVG and hatch SVG, store on the client
        from nhc.rendering.svg import render_floor_svg, render_hatch_svg
        if game.level:
            logger.info("Rendering floor SVG...")
            seed = game.seed or 0
            client.floor_svg = render_floor_svg(
                game.level, seed=seed,
            )
            client.hatch_svg = render_hatch_svg(seed=seed)
            logger.info("Floor SVG: %d bytes, Hatch SVG: %d bytes",
                         len(client.floor_svg), len(client.hatch_svg))
        else:
            logger.warning("No level — floor SVG not generated")

        logger.info("Session %s ready, waiting for WS connection",
                     session.session_id)
        return jsonify({
            "session_id": session.session_id,
            "lang": session.lang,
            "tileset": session.tileset,
            "god_mode": config.god_mode,
        }), 201

    @app.route("/api/game/<session_id>/debug.json", methods=["GET"])
    @_maybe_auth
    def game_debug_data(session_id: str):
        session = sessions.get(session_id)
        if not session:
            return jsonify({"error": "session not found"}), 404
        if not session.game.god_mode or not session.game.level:
            return jsonify({"error": "not available"}), 404
        client = session.game.renderer
        resp = jsonify(client._gather_debug_data(session.game.level))
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp

    @app.route("/api/game/<session_id>/labels.json", methods=["GET"])
    @_maybe_auth
    def game_labels(session_id: str):
        session = sessions.get(session_id)
        if not session:
            return jsonify({"error": "session not found"}), 404
        client = session.game.renderer
        resp = jsonify(client._action_labels())
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp

    @app.route("/api/game/<session_id>/floor.svg", methods=["GET"])
    @_maybe_auth
    def game_floor_svg(session_id: str):
        session = sessions.get(session_id)
        if not session:
            return "session not found", 404
        client = session.game.renderer
        if not client.floor_svg:
            return "floor SVG not generated", 404
        resp = make_response(client.floor_svg)
        resp.headers["Content-Type"] = "image/svg+xml"
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp

    @app.route("/api/game/<session_id>/hatch.svg", methods=["GET"])
    @_maybe_auth
    def game_hatch_svg(session_id: str):
        session = sessions.get(session_id)
        if not session:
            return "session not found", 404
        client = session.game.renderer
        if not client.hatch_svg:
            return "hatch not generated", 404
        resp = make_response(client.hatch_svg)
        resp.headers["Content-Type"] = "image/svg+xml"
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp

    # ── Export routes (god mode only) ───────────────────────────

    @app.route("/api/game/<session_id>/export/game_state",
               methods=["POST"])
    @_maybe_auth
    def export_game_state(session_id: str):
        session = sessions.get(session_id)
        if not session or not session.game.god_mode:
            return jsonify({"error": "not available"}), 404
        import json as _json
        from datetime import datetime
        from pathlib import Path as _Path
        from nhc.core.save import _serialize_entities, _serialize_level
        game = session.game
        client = game.renderer
        static, dynamic = client._gather_stats(
            game.world, game.player_id, game.turn, game.level)
        data = {
            "timestamp": datetime.now().isoformat(),
            "turn": game.turn,
            "player_id": game.player_id,
            "seed": game.seed,
            "stats": {**static, **dynamic},
            "entities": client._gather_entities(
                game.world, game.level, game.player_id),
            "level": _serialize_level(game.level),
            "ecs": _serialize_entities(game.world),
        }
        out = _Path("debug/exports")
        out.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = out / f"game_state_{ts}.json"
        path.write_text(_json.dumps(data, indent=2))
        logger.info("Exported game state: %s", path)
        return jsonify({"path": str(path)})

    @app.route("/api/game/<session_id>/export/layer_state",
               methods=["POST"])
    @_maybe_auth
    def export_layer_state(session_id: str):
        session = sessions.get(session_id)
        if not session or not session.game.god_mode:
            return jsonify({"error": "not available"}), 404
        import json as _json
        from datetime import datetime
        from pathlib import Path as _Path
        from nhc.dungeon.model import Terrain
        game = session.game
        client = game.renderer
        level = game.level
        # Explored tiles
        explored = []
        for y in range(level.height):
            for x in range(level.width):
                tile = level.tile_at(x, y)
                if tile and tile.explored:
                    explored.append([x, y])
        data = {
            "timestamp": datetime.now().isoformat(),
            "turn": game.turn,
            "fov": client._gather_fov(level),
            "explored": explored,
            "doors": client._gather_doors(level),
            "debug": client._gather_debug_data(level),
        }
        out = _Path("debug/exports")
        out.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = out / f"layer_state_{ts}.json"
        path.write_text(_json.dumps(data, indent=2))
        logger.info("Exported layer state: %s", path)
        return jsonify({"path": str(path)})

    @app.route("/api/game/<session_id>/export/map_svg",
               methods=["POST"])
    @_maybe_auth
    def export_map_svg(session_id: str):
        session = sessions.get(session_id)
        if not session or not session.game.god_mode:
            return jsonify({"error": "not available"}), 404
        from datetime import datetime
        from pathlib import Path as _Path
        client = session.game.renderer
        if not client.floor_svg:
            return jsonify({"error": "no SVG"}), 404
        out = _Path("debug/exports")
        out.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = out / f"map_{ts}.svg"
        path.write_text(client.floor_svg)
        logger.info("Exported map SVG: %s", path)
        return jsonify({"path": str(path)})

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

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({
            "status": "ok",
            "sessions": sessions.active_count,
        })

    return app


def app_factory() -> Flask:
    """WSGI app factory for gunicorn. Reads config from env vars."""
    import os
    from pathlib import Path

    data_dir_str = os.environ.get("NHC_DATA_DIR")
    data_dir = Path(data_dir_str) if data_dir_str else None

    config = WebConfig(
        host="0.0.0.0",
        port=int(os.environ.get("NHC_PORT", "8080")),
        max_sessions=int(os.environ.get("NHC_MAX_SESSIONS", "8")),
        data_dir=data_dir,
        auth_required=bool(os.environ.get("NHC_AUTH_TOKEN")),
        god_mode=False,
    )
    auth_token = os.environ.get("NHC_AUTH_TOKEN")
    return create_app(config, auth_token=auth_token)
