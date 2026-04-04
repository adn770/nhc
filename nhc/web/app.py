"""Flask application factory for the nhc web server."""

from __future__ import annotations

import asyncio
import collections
import logging
import time
from pathlib import Path

from flask import (
    Flask, g, jsonify, make_response, render_template, request, send_file,
)
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
    """Create and configure the Flask application.

    *auth_token* is the **admin** token.  Player tokens are managed
    via the :class:`~nhc.web.registry.PlayerRegistry`.
    """
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
    app.config["LOG_PATH"] = str(log_path)
    logger.info("Log file: %s", log_path)

    sessions = SessionManager(config)
    app.config["SESSIONS"] = sessions

    # Pre-generate the hatch SVG once — it's seed-independent and
    # shared across all games so we serve it as a static asset.
    from nhc.rendering.svg import render_hatch_svg
    _hatch_svg = render_hatch_svg(seed=0)
    logger.info("Hatch SVG generated at startup: %d bytes", len(_hatch_svg))

    _limiter = _RateLimiter(max_requests=5, window=60)

    def _check_rate_limit():
        ip = request.remote_addr or "unknown"
        if not _limiter.is_allowed(ip):
            return jsonify({"error": "rate limit exceeded"}), 429
        return None

    # ── Auth setup ──────────────────────────────────────────

    admin_hash: str = ""
    if auth_token:
        from nhc.web.auth import hash_token
        admin_hash = hash_token(auth_token)
    # Legacy — kept for backward compat in tests that check it
    app.config["AUTH_HASHES"] = {admin_hash} if admin_hash else set()

    # Player registry (persistent)
    from nhc.web.registry import PlayerRegistry
    registry = None
    if config.data_dir:
        registry = PlayerRegistry(config.data_dir / "players.json")
        registry.load()
    app.config["PLAYER_REGISTRY"] = registry

    # Auth decorator wrappers
    def _player_auth(f):
        """Apply player token auth when auth is enabled."""
        if config.auth_required and registry:
            from nhc.web.auth import require_player
            return require_player(registry)(f)
        return f

    def _admin_auth(f):
        """Apply admin token + LAN auth when auth is enabled."""
        if config.auth_required and admin_hash:
            from nhc.web.auth import require_admin
            return require_admin(admin_hash)(f)
        return f

    sock = Sock(app)

    # Register WebSocket routes
    from nhc.web.ws import register_ws
    register_ws(app, sock)

    # ── Helpers ─────────────────────────────────────────────

    def _create_llm_backend():
        """Try to create LLM backend, return None on failure."""
        try:
            from nhc.utils.llm import create_backend
            return create_backend({
                "provider": "ollama",
                "model": config.ollama_model,
                "url": config.ollama_url,
                "temp": 0.1,
                "ctx": 16384,
            })
        except Exception:
            logger.debug("LLM backend unavailable, running without")
            return None

    def _player_save_dir(pid: str) -> Path | None:
        """Return the save directory for a player, or None."""
        if not config.data_dir:
            return None
        return config.data_dir / "players" / pid

    def _get_player_id() -> str:
        """Get current player_id from auth context or request body."""
        pid = getattr(g, "player_id", "") or ""
        if not pid:
            # Fallback: derive from token in request body (no-auth mode)
            data = request.get_json(silent=True) or {}
            token = data.get("player_token", "")
            if token:
                pid = player_id_from_token(token)
        return pid

    # ── Public routes ───────────────────────────────────────

    @app.route("/")
    def index():
        if config.auth_required and registry:
            from nhc.web.auth import _extract_token, hash_token
            token = _extract_token()
            if not token:
                return ("Authentication required."
                        " Use the link provided by your admin."), 401
            h = hash_token(token)
            if not registry.is_valid_token_hash(h):
                return "Invalid or revoked token.", 403
            pid = registry.player_id_for_hash(h)
            player = registry.get(pid)
            player_name = player["name"] if player else ""
            player_god = player.get("god_mode", False) if player else False
            player_lang = player.get("lang", "") if player else ""
            resp = make_response(render_template(
                "index.html", player_name=player_name,
                god_mode=player_god, player_lang=player_lang,
            ))
            resp.set_cookie("nhc_token", token,
                            samesite="Strict")
            return resp
        return render_template("index.html")

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({
            "status": "ok",
            "sessions": sessions.active_count,
        })

    @app.route("/api/tilesets", methods=["GET"])
    def tilesets():
        return jsonify(["classic"])

    @app.route("/api/help/<lang>", methods=["GET"])
    def help_text(lang: str):
        """Serve the help document for the given language."""
        docs = Path(__file__).parent.parent.parent / "docs"
        path = docs / f"help_{lang}.md"
        if not path.exists():
            path = docs / "help_en.md"
        if not path.exists():
            return "Help not available.", 404
        return path.read_text(), 200, {"Content-Type": "text/plain"}

    # ── Admin routes (LAN + admin token) ────────────────────

    @app.route("/admin")
    @_admin_auth
    def admin_page():
        from nhc.web.auth import _extract_token
        token = _extract_token(cookie_name="nhc_admin_token")
        resp = make_response(render_template(
            "admin.html", external_url=config.external_url,
        ))
        if token:
            resp.set_cookie("nhc_admin_token", token, httponly=True,
                            samesite="Strict", path="/")
        return resp

    @app.route("/api/admin/players", methods=["GET"])
    @_admin_auth
    def admin_list_players():
        if not registry:
            return jsonify([])
        players = registry.list_all()
        for p in players:
            session = sessions.get_by_player(p["player_id"])
            p["online"] = session.connected if session else False
            p["has_session"] = session is not None
            from nhc.core.autosave import has_autosave
            save_dir = _player_save_dir(p["player_id"])
            p["has_save"] = has_autosave(save_dir) if save_dir else False
        return jsonify(players)

    @app.route("/api/admin/players", methods=["POST"])
    @_admin_auth
    def admin_register_player():
        blocked = _check_rate_limit()
        if blocked:
            return blocked
        if not registry:
            return jsonify({"error": "no data_dir configured"}), 500
        data = request.get_json(silent=True) or {}
        name = data.get("name", "").strip()
        if not name:
            return jsonify({"error": "name required"}), 400
        token, player_id = registry.register(name)
        save_dir = _player_save_dir(player_id)
        if save_dir:
            save_dir.mkdir(parents=True, exist_ok=True)
        return jsonify({
            "player_id": player_id,
            "token": token,
            "name": name,
        }), 201

    @app.route("/api/admin/players/<player_id>/regenerate",
               methods=["POST"])
    @_admin_auth
    def admin_regenerate_token(player_id: str):
        if not registry:
            return jsonify({"error": "no registry"}), 500
        token = registry.regenerate_token(player_id)
        if token:
            return jsonify({"player_id": player_id, "token": token})
        return jsonify({"error": "player not found or revoked"}), 404

    @app.route("/api/admin/players/<player_id>", methods=["DELETE"])
    @_admin_auth
    def admin_revoke_player(player_id: str):
        if not registry:
            return jsonify({"error": "no registry"}), 500
        if registry.revoke(player_id):
            return jsonify({"status": "revoked"})
        return jsonify({"error": "player not found"}), 404

    @app.route(
        "/api/admin/players/<player_id>/god_mode", methods=["POST"],
    )
    @_admin_auth
    def admin_toggle_god_mode(player_id: str):
        if not registry:
            return jsonify({"error": "no registry"}), 500
        data = request.get_json(silent=True) or {}
        enabled = bool(data.get("enabled", False))
        if not registry.set_god_mode(player_id, enabled):
            return jsonify({"error": "player not found"}), 404
        # Live toggle on active session
        session = sessions.get_by_player(player_id)
        if session and session.game:
            session.game.set_god_mode(enabled)
        return jsonify({"status": "ok", "god_mode": enabled})

    @app.route("/api/admin/sessions", methods=["GET"])
    @_admin_auth
    def admin_list_sessions():
        return jsonify(sessions.list_sessions())

    @app.route("/api/admin/debug-bundle", methods=["GET"])
    @_admin_auth
    def admin_debug_bundle():
        import io
        import tarfile

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            # 1. Game log
            log_file = Path(app.config.get("LOG_PATH", ""))
            if log_file.exists():
                tar.add(str(log_file), arcname="nhc.log")

            # 2. Debug exports
            exports_dir = Path("debug/exports")
            if exports_dir.exists():
                for f in exports_dir.iterdir():
                    if f.is_file():
                        tar.add(str(f), arcname=f"exports/{f.name}")

            # 3. Current floor SVGs from active sessions
            for s in sessions.list_sessions():
                sess = sessions.get(s["session_id"])
                if not sess or not sess.game:
                    continue
                for depth, (svg_id, svg) in sess.game._svg_cache.items():
                    pid = sess.player_id or "anon"
                    info = tarfile.TarInfo(
                        name=f"svg/{pid}_depth{depth}.svg",
                    )
                    svg_bytes = svg.encode("utf-8")
                    info.size = len(svg_bytes)
                    tar.addfile(info, io.BytesIO(svg_bytes))

            # 4. Autosave files
            data_dir = config.data_dir
            if data_dir:
                players_dir = data_dir / "players"
                if players_dir.exists():
                    for player_dir in players_dir.iterdir():
                        if not player_dir.is_dir():
                            continue
                        autosave = player_dir / "autosave.nhc"
                        if autosave.exists():
                            tar.add(
                                str(autosave),
                                arcname=(
                                    f"autosaves/{player_dir.name}"
                                    f"/autosave.nhc"
                                ),
                            )

        buf.seek(0)
        return send_file(
            buf,
            mimetype="application/gzip",
            as_attachment=True,
            download_name="nhc-debug-bundle.tar.gz",
        )

    # ── Player routes (player token) ────────────────────────

    @app.route("/api/player/login", methods=["POST"])
    @_player_auth
    def player_login():
        pid = _get_player_id()
        save_dir = _player_save_dir(pid)
        from nhc.core.autosave import has_autosave
        has_save = has_autosave(save_dir) if save_dir else has_autosave()
        existing = sessions.get_by_player(pid)
        return jsonify({
            "player_id": pid,
            "has_save": has_save,
            "active_session": existing.session_id if existing else None,
        })

    @app.route("/api/game/has_save", methods=["GET"])
    @_player_auth
    def game_has_save():
        pid = _get_player_id()
        save_dir = _player_save_dir(pid)
        from nhc.core.autosave import has_autosave
        return jsonify({
            "has_save": has_autosave(save_dir) if save_dir else has_autosave(),
        })

    @app.route("/api/game/resume", methods=["POST"])
    @_player_auth
    def game_resume():
        pid = _get_player_id()
        if not pid:
            return jsonify({"error": "player identity required"}), 400
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
                "god_mode": existing.game.god_mode,
            })

        # No active session — check for autosave on disk
        from nhc.core.autosave import has_autosave
        if not has_autosave(save_dir):
            return jsonify({"has_save": False})

        # Create a new session and restore from autosave
        data = request.get_json(silent=True) or {}
        lang = data.get("lang", "")
        tileset = data.get("tileset", "")
        try:
            session = sessions.create(
                lang=lang, tileset=tileset,
                player_id=pid, save_dir=save_dir,
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 429

        # Persist language preference for returning players
        if registry and session.lang:
            registry.set_lang(pid, session.lang)

        from nhc.i18n import init as i18n_init
        i18n_init(session.lang)

        from nhc.core.game import Game
        from nhc.rendering.web_client import WebClient

        client = WebClient(game_mode="classic", lang=session.lang)
        backend = _create_llm_backend()

        player_god = config.god_mode
        if registry and pid:
            pdata = registry.get(pid)
            if pdata:
                player_god = pdata.get("god_mode", False)
        game = Game(
            client=client,
            backend=backend,
            game_mode="classic",
            shape_variety=config.shape_variety,
            god_mode=player_god,
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

        # Load cached floor SVG or re-render
        import uuid as _uuid
        from nhc.core.autosave import load_svg_cache, save_svg_cache
        depth = game.level.depth if game.level else 1
        svg_cached = game._svg_cache.get(depth)
        if svg_cached:
            client.floor_svg_id, client.floor_svg = svg_cached
            logger.info("Resume: floor SVG from game cache: %s",
                        client.floor_svg_id)
        else:
            cached = load_svg_cache(save_dir)
            if cached:
                client.floor_svg = cached[0]
                client.floor_svg_id = _uuid.uuid4().hex[:12]
                logger.info("Resume: floor SVG from disk cache")
            elif game.level:
                from nhc.rendering.svg import render_floor_svg
                seed = game.seed or 0
                client.floor_svg = render_floor_svg(
                    game.level, seed=seed,
                    hatch_distance=config.hatch_distance,
                )
                client.floor_svg_id = _uuid.uuid4().hex[:12]
                save_svg_cache(client.floor_svg, _hatch_svg, save_dir)
            if client.floor_svg and game.level:
                game._svg_cache[depth] = (
                    client.floor_svg_id, client.floor_svg,
                )

        logger.info("Resume: restored session %s for player %s (turn=%d)",
                     session.session_id, pid, game.turn)
        return jsonify({
            "session_id": session.session_id,
            "resumed": True,
            "turn": game.turn,
            "god_mode": game.god_mode,
        }), 201

    @app.route("/api/game/new", methods=["POST"])
    @_player_auth
    def game_new():
        blocked = _check_rate_limit()
        if blocked:
            return blocked
        data = request.get_json(silent=True) or {}
        lang = data.get("lang", "")
        tileset = data.get("tileset", "")
        reset = data.get("reset", False) or config.reset
        pid = _get_player_id()

        # Destroy any stale suspended session for this player
        if pid:
            old = sessions.get_by_player(pid)
            if old:
                logger.info("Destroying stale session %s for player %s",
                            old.session_id, pid)
                sessions.destroy(old.session_id)

        save_dir = _player_save_dir(pid) if pid else None
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

        # Persist language preference for returning players
        if registry and pid and session.lang:
            registry.set_lang(pid, session.lang)

        # Initialize i18n and create the game instance
        from nhc.i18n import init as i18n_init
        i18n_init(session.lang)

        from nhc.core.game import Game
        from nhc.rendering.web_client import WebClient

        client = WebClient(game_mode="classic", lang=session.lang)
        backend = _create_llm_backend()
        logger.debug("LLM backend: %s", type(backend).__name__
                      if backend else "None")

        player_god = config.god_mode
        if registry and pid:
            pdata = registry.get(pid)
            if pdata:
                player_god = pdata.get("god_mode", False)
        game = Game(
            client=client,
            backend=backend,
            game_mode="classic",
            reset=reset,
            shape_variety=config.shape_variety,
            god_mode=player_god,
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

        # Generate floor SVG; hatch is served globally.
        import uuid as _uuid
        from nhc.core.autosave import load_svg_cache, save_svg_cache
        depth = game.level.depth if game.level else 1
        svg_cached = game._svg_cache.get(depth)
        if svg_cached:
            client.floor_svg_id, client.floor_svg = svg_cached
            logger.info("Floor SVG from game cache: %s (%d bytes)",
                        client.floor_svg_id, len(client.floor_svg))
        else:
            cached = load_svg_cache(session.save_dir)
            if cached:
                client.floor_svg = cached[0]
                client.floor_svg_id = _uuid.uuid4().hex[:12]
                logger.info("Floor SVG from disk cache: %d bytes",
                            len(client.floor_svg))
            elif game.level:
                from nhc.rendering.svg import render_floor_svg
                logger.info("Rendering floor SVG...")
                seed = game.seed or 0
                client.floor_svg = render_floor_svg(
                    game.level, seed=seed,
                    hatch_distance=config.hatch_distance,
                )
                client.floor_svg_id = _uuid.uuid4().hex[:12]
                logger.info("Floor SVG: %s (%d bytes)",
                            client.floor_svg_id, len(client.floor_svg))
                save_svg_cache(
                    client.floor_svg, _hatch_svg, session.save_dir,
                )
            else:
                logger.warning("No level — floor SVG not generated")
            # Store in game SVG cache for future transitions
            if client.floor_svg and game.level:
                game._svg_cache[depth] = (
                    client.floor_svg_id, client.floor_svg,
                )

        logger.info("Session %s ready, waiting for WS connection",
                     session.session_id)
        return jsonify({
            "session_id": session.session_id,
            "lang": session.lang,
            "tileset": session.tileset,
            "god_mode": game.god_mode,
        }), 201

    @app.route("/api/game/<session_id>/debug.json", methods=["GET"])
    @_player_auth
    def game_debug_data(session_id: str):
        session = sessions.get(session_id)
        if not session:
            return jsonify({"error": "session not found"}), 404
        if not session.game.god_mode or not session.game.level:
            return jsonify({"error": "not available"}), 404
        client = session.game.renderer
        resp = jsonify(client._gather_debug_data(session.game.level))
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    @app.route("/api/game/<session_id>/labels.json", methods=["GET"])
    @_player_auth
    def game_labels(session_id: str):
        session = sessions.get(session_id)
        if not session:
            return jsonify({"error": "session not found"}), 404
        client = session.game.renderer
        resp = jsonify(client._action_labels())
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp

    @app.route("/api/game/<session_id>/floor/<svg_id>.svg",
               methods=["GET"])
    @_player_auth
    def game_floor_svg(session_id: str, svg_id: str):
        session = sessions.get(session_id)
        if not session:
            return "session not found", 404
        client = session.game.renderer
        if not client.floor_svg:
            return "floor SVG not generated", 404
        resp = make_response(client.floor_svg)
        resp.headers["Content-Type"] = "image/svg+xml"
        resp.headers["Cache-Control"] = "public, max-age=604800"
        return resp

    @app.route("/api/hatch.svg", methods=["GET"])
    def global_hatch_svg():
        resp = make_response(_hatch_svg)
        resp.headers["Content-Type"] = "image/svg+xml"
        resp.headers["Cache-Control"] = "public, max-age=604800"
        return resp

    # ── Generation params / regenerate (god mode only) ──────

    @app.route("/api/game/<session_id>/generation_params",
               methods=["GET"])
    @_player_auth
    def game_generation_params(session_id: str):
        """Return current dungeon generation parameters."""
        session = sessions.get(session_id)
        if not session or not session.game.god_mode:
            return jsonify({"error": "not available"}), 404
        params = session.game.generation_params
        if not params:
            return jsonify({"error": "no params available"}), 404
        return jsonify(params.to_dict())

    @app.route("/api/game/<session_id>/regenerate", methods=["POST"])
    @_player_auth
    def game_regenerate(session_id: str):
        """Regenerate the dungeon with custom parameters."""
        session = sessions.get(session_id)
        if not session or not session.game.god_mode:
            return jsonify({"error": "not available"}), 404

        data = request.get_json(silent=True) or {}
        from nhc.dungeon.generator import GenerationParams
        from nhc.dungeon.generators.bsp import BSPGenerator
        from nhc.dungeon.generators.cellular import CellularGenerator
        from nhc.dungeon.populator import populate_level
        from nhc.dungeon.room_types import assign_room_types
        from nhc.dungeon.terrain import apply_terrain
        from nhc.dungeon.themes import theme_for_depth
        from nhc.utils.rng import get_rng, get_seed, set_seed

        # Fill in theme from depth if not explicitly provided
        if "theme" not in data and "depth" in data:
            data["theme"] = theme_for_depth(data["depth"])

        try:
            params = GenerationParams.from_dict(data)
        except (TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400

        game = session.game
        client = game.renderer

        # Set seed
        if params.seed is not None:
            set_seed(params.seed)
        else:
            set_seed(None)
        game.seed = get_seed()
        params.seed = game.seed

        # Remove non-player entities (keep player + inventory)
        player_inv = game.world.get_component(
            game.player_id, "Inventory",
        )
        keep_ids = {game.player_id}
        if player_inv:
            keep_ids.update(player_inv.slots)
        for eid in list(game.world._entities):
            if eid not in keep_ids:
                game.world.destroy_entity(eid)

        # Generate new level
        gen = (CellularGenerator() if params.theme == "cave"
               else BSPGenerator())
        game.level = gen.generate(params)
        game.generation_params = params
        rng = get_rng()
        assign_room_types(game.level, rng)
        apply_terrain(game.level, rng)
        populate_level(game.level)
        game._spawn_level_entities()

        # Place player at stairs_up
        pos = game.world.get_component(game.player_id, "Position")
        if pos:
            for y in range(game.level.height):
                for x in range(game.level.width):
                    tile = game.level.tile_at(x, y)
                    if tile and tile.feature == "stairs_up":
                        pos.x = x
                        pos.y = y
                        pos.level_id = game.level.id
                        break
                else:
                    continue
                break

        # Reset FOV tracking and update
        game._seen_creatures.clear()
        game._update_fov()

        # Push new floor to client (renders SVG, resets deltas,
        # sends floor + debug_url messages via output queue)
        client.send_floor_change(
            game.level, game.world, game.player_id,
            game.turn, seed=game.seed or 0,
            hatch_distance=config.hatch_distance,
        )
        game._svg_cache[params.depth] = (
            client.floor_svg_id, client.floor_svg,
        )
        # Send debug_url so overlays refresh
        import json as _json
        base_url = f"/api/game/{session_id}"
        client._send({
            "type": "debug_url",
            "url": f"{base_url}/debug.json",
        })

        logger.info(
            "Regenerated level: depth=%d theme=%s seed=%d "
            "(%dx%d, %d rooms)",
            params.depth, params.theme, game.seed,
            game.level.width, game.level.height,
            len(game.level.rooms),
        )

        return jsonify({
            "status": "ok",
            "seed": game.seed,
            "params": params.to_dict(),
        })

    # ── Export routes (god mode only) ───────────────────────

    @app.route("/api/game/<session_id>/export/game_state",
               methods=["POST"])
    @_player_auth
    def export_game_state(session_id: str):
        session = sessions.get(session_id)
        if not session or not session.game.god_mode:
            return jsonify({"error": "not available"}), 404
        import json as _json
        from datetime import datetime
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
        out = Path("debug/exports")
        out.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = out / f"game_state_{ts}.json"
        path.write_text(_json.dumps(data, indent=2))
        logger.info("Exported game state: %s", path)
        return jsonify({"path": str(path)})

    @app.route("/api/game/<session_id>/export/layer_state",
               methods=["POST"])
    @_player_auth
    def export_layer_state(session_id: str):
        session = sessions.get(session_id)
        if not session or not session.game.god_mode:
            return jsonify({"error": "not available"}), 404
        import json as _json
        from datetime import datetime
        game = session.game
        client = game.renderer
        level = game.level
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
        out = Path("debug/exports")
        out.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = out / f"layer_state_{ts}.json"
        path.write_text(_json.dumps(data, indent=2))
        logger.info("Exported layer state: %s", path)
        return jsonify({"path": str(path)})

    @app.route("/api/game/<session_id>/export/map_svg",
               methods=["POST"])
    @_player_auth
    def export_map_svg(session_id: str):
        session = sessions.get(session_id)
        if not session or not session.game.god_mode:
            return jsonify({"error": "not available"}), 404
        from datetime import datetime
        client = session.game.renderer
        if not client.floor_svg:
            return jsonify({"error": "no SVG"}), 404
        out = Path("debug/exports")
        out.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = out / f"map_{ts}.svg"
        path.write_text(client.floor_svg)
        logger.info("Exported map SVG: %s", path)
        return jsonify({"path": str(path)})

    @app.route("/api/game/<session_id>/export/bundle", methods=["GET"])
    @_player_auth
    def export_debug_bundle(session_id: str):
        """Build a tar.gz with all debug data for this session."""
        session = sessions.get(session_id)
        if not session or not session.game.god_mode:
            return jsonify({"error": "not available"}), 404

        import io
        import json as _json
        import tarfile
        from datetime import datetime

        game = session.game
        client = game.renderer
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Force a fresh autosave so the bundle always contains
        # the current game state.
        if session.save_dir:
            from nhc.core.autosave import autosave as _autosave
            _autosave(game, session.save_dir, blocking=True)

        def _add_text(tar, name, text):
            data = text.encode("utf-8")
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            # 1. Game state JSON (MCP expects exports/game_state_*.json)
            from nhc.core.save import _serialize_entities, _serialize_level
            static, dynamic = client._gather_stats(
                game.world, game.player_id, game.turn, game.level)
            gen_params = (game.generation_params.to_dict()
                          if game.generation_params else None)
            state = {
                "timestamp": datetime.now().isoformat(),
                "turn": game.turn,
                "player_id": game.player_id,
                "seed": game.seed,
                "level_id": game.level.id if game.level else None,
                "floor_svg_id": client.floor_svg_id,
                "generation_params": gen_params,
                "stats": {**static, **dynamic},
                "entities": client._gather_entities(
                    game.world, game.level, game.player_id),
                "level": _serialize_level(game.level),
                "ecs": _serialize_entities(game.world),
            }
            _add_text(tar, f"exports/game_state_{ts}.json",
                      _json.dumps(state, indent=2))

            # 2. Layer state JSON
            level = game.level
            explored = [[x, y]
                        for y in range(level.height)
                        for x in range(level.width)
                        if (t := level.tile_at(x, y)) and t.explored]
            layer = {
                "timestamp": datetime.now().isoformat(),
                "turn": game.turn,
                "fov": client._gather_fov(level),
                "explored": explored,
                "doors": client._gather_doors(level),
                "debug": client._gather_debug_data(level),
            }
            _add_text(tar, f"exports/layer_state_{ts}.json",
                      _json.dumps(layer, indent=2))

            # 3. Floor SVGs (all cached depths)
            for depth, (svg_id, svg) in game._svg_cache.items():
                _add_text(tar, f"exports/map_{ts}_d{depth}.svg", svg)

            # 4. Autosave
            if session.save_dir:
                autosave = session.save_dir / "autosave.nhc"
                if autosave.exists():
                    tar.add(str(autosave), arcname="autosave.nhc")

            # 5. Game log
            log_file = Path(app.config.get("LOG_PATH", ""))
            if log_file.exists():
                tar.add(str(log_file), arcname="nhc.log")

            # 6. Generation params (standalone for easy access)
            if gen_params:
                _add_text(
                    tar,
                    f"exports/generation_params_{ts}.json",
                    _json.dumps(gen_params, indent=2),
                )

        buf.seek(0)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return send_file(
            buf,
            mimetype="application/gzip",
            as_attachment=True,
            download_name=f"nhc-debug-{session_id[:12]}-{ts}.tar.gz",
        )

    @app.route("/api/game/list", methods=["GET"])
    @_player_auth
    def game_list():
        return jsonify(sessions.list_sessions())

    @app.route("/api/game/<session_id>", methods=["DELETE"])
    @_player_auth
    def game_delete(session_id: str):
        if sessions.destroy(session_id):
            return jsonify({"status": "ok"})
        return jsonify({"error": "session not found"}), 404

    return app


def app_factory() -> Flask:
    """WSGI app factory for gunicorn. Reads config from env vars."""
    import os

    data_dir_str = os.environ.get("NHC_DATA_DIR")
    data_dir = Path(data_dir_str) if data_dir_str else None

    config = WebConfig(
        host="0.0.0.0",
        port=int(os.environ.get("NHC_PORT", "8080")),
        max_sessions=int(os.environ.get("NHC_MAX_SESSIONS", "8")),
        data_dir=data_dir,
        auth_required=bool(os.environ.get("NHC_AUTH_TOKEN")),
        god_mode=False,
        hatch_distance=float(os.environ.get("NHC_HATCH_DISTANCE", "1.0")),
        external_url=os.environ.get("NHC_EXTERNAL_URL", ""),
    )
    auth_token = os.environ.get("NHC_AUTH_TOKEN")
    return create_app(config, auth_token=auth_token)
