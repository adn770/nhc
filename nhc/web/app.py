"""Flask application factory for the nhc web server."""

from __future__ import annotations

import atexit
import collections
import ipaddress
import logging
import multiprocessing
import os
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from flask import (
    Flask, abort, g, jsonify, make_response, redirect, render_template,
    request, send_file, send_from_directory, url_for,
)
from flask_sock import Sock
from werkzeug.middleware.proxy_fix import ProxyFix

from nhc.web.config import WebConfig
from nhc.web.sessions import SessionManager, player_id_from_token

logger = logging.getLogger(__name__)


def _get_tts_engine(app: Flask) -> "TTSEngine":
    """Return the shared TTSEngine singleton, creating it lazily."""
    engine = app.config.get("TTS_ENGINE")
    if engine is None:
        from nhc.web.tts import TTSEngine
        engine = TTSEngine()
        app.config["TTS_ENGINE"] = engine
    return engine


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

    # Behind Caddy (or any single trusted upstream proxy),
    # ``request.remote_addr`` is the proxy's loopback IP.  ProxyFix
    # rewrites it from the ``X-Forwarded-For`` header set by the
    # proxy so downstream code can allowlist real client IPs.
    # Only enable when explicitly configured — a bare-metal dev
    # server must NOT trust forwarded headers from random clients.
    if config.trust_proxy:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    # Empty list is interpreted as "fail closed": admin is reachable
    # only from CIDRs listed here, so a missing configuration means
    # no admin at all rather than any-client-accepted.
    admin_lan_networks: list[ipaddress.IPv4Network
                              | ipaddress.IPv6Network] = []
    for cidr in config.admin_lan_cidrs:
        try:
            admin_lan_networks.append(ipaddress.ip_network(cidr))
        except ValueError:
            logger.error("Ignoring invalid admin_lan_cidrs entry: %s",
                         cidr)
    if config.auth_required and not admin_lan_networks:
        logger.warning(
            "NHC_ADMIN_LAN_CIDRS is empty — /admin will be "
            "unreachable. Set NHC_ADMIN_LAN_CIDRS to a CIDR "
            "like 192.168.18.0/24 to enable admin access.",
        )

    # Cache-busting version for static JS/CSS files
    _static_version = str(int(time.time()))

    @app.context_processor
    def _inject_static_version():
        return {"v": _static_version}

    # Set up file + console logging via shared log_utils. The
    # server logs land outside the project's debug/ tree so that
    # routine debug-dir cleanups don't wipe an in-flight session.
    from nhc.utils.log import setup_logging
    server_log = Path.home() / "src" / "nhc-server.log"
    log_path = setup_logging(
        level=logging.DEBUG,
        debug_topics="all",
        log_file=str(server_log),
        console_output=True,
    )
    app.config["LOG_PATH"] = str(log_path)
    logger.info("Log file: %s", log_path)

    sessions = SessionManager(config)
    app.config["SESSIONS"] = sessions

    # Discover entity factories once at startup. Previously this ran
    # on every game.initialize() call, putting import I/O on the hot
    # path for concurrent sessions.
    from nhc.entities.registry import EntityRegistry
    EntityRegistry.discover_all()

    # ProcessPoolExecutor for CPU-bound dungeon generation. Each
    # gthread worker thread handling a request submits generation to
    # the shared pool and blocks on the future's result — other
    # threads in the same worker keep serving traffic in parallel.
    # Sized via NHC_GEN_WORKERS (default: cpu count). Workers are
    # long-lived and reused across requests.
    #
    # Pinned to the 'spawn' start method. Even under gthread, fork()
    # inside a multi-threaded parent is unsafe (fork-locks, duplicate
    # file descriptors, half-held locks from other threads). Spawn
    # re-execs a clean Python interpreter per worker process and
    # re-imports the dungeon modules once at startup.
    gen_workers = int(
        os.environ.get("NHC_GEN_WORKERS", str(os.cpu_count() or 1))
    )
    mp_ctx = multiprocessing.get_context("spawn")
    gen_pool = ProcessPoolExecutor(
        max_workers=gen_workers, mp_context=mp_ctx
    )
    app.config["GEN_POOL"] = gen_pool
    logger.info("Generation pool: %d worker(s)", gen_workers)
    # Shut the pool down on interpreter exit so tests and dev reloads
    # don't leak worker processes.
    atexit.register(gen_pool.shutdown, wait=False, cancel_futures=True)

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

    # Leaderboard (persistent).  Scores are submitted server-side
    # when a run ends (death or victory); see nhc.web.ws.
    from nhc.web.leaderboard import Leaderboard
    leaderboard_path = (
        (config.data_dir / "leaderboard.json")
        if config.data_dir
        else Path(tempfile.gettempdir()) / "nhc_leaderboard.json"
    )
    leaderboard = Leaderboard(leaderboard_path)
    leaderboard.load()
    app.config["LEADERBOARD"] = leaderboard

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
            return require_admin(
                admin_hash, lan_networks=admin_lan_networks,
            )(f)
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

    def _set_auth_cookie(resp, name: str, token: str,
                         *, path: str = "/") -> None:
        """Write a short-lived auth cookie with the strict defaults
        every auth route in this app shares — ``HttpOnly``,
        ``SameSite=Strict``, and ``Secure`` whenever the request
        arrived over HTTPS."""
        resp.set_cookie(
            name, token,
            httponly=True, samesite="Strict", path=path,
            secure=request.is_secure,
        )

    def _token_strip_redirect(endpoint: str, cookie_name: str,
                              token: str, *, path: str = "/"):
        """303-redirect to *endpoint* without the ``?token=``, and
        set the auth cookie on the way out.  Called when a token
        arrives in the URL bar so it does not linger in history,
        access logs, or ``Referer`` headers."""
        resp = redirect(url_for(endpoint), code=303)
        _set_auth_cookie(resp, cookie_name, token, path=path)
        return resp

    # ── Public routes ───────────────────────────────────────

    def _welcome_labels(lang: str) -> dict:
        """Return the label subset the welcome screen/ranking modal
        needs before a game session exists.  Initializes i18n on
        the request thread so translations match the player's lang.
        """
        from nhc.i18n import init as i18n_init, t as tr
        i18n_init(lang or config.default_lang)
        keys = [
            "ranking_button", "ranking_title", "ranking_empty",
            "ranking_col_rank", "ranking_col_name", "ranking_col_score",
            "ranking_col_depth", "ranking_col_turns", "ranking_col_fate",
            "ranking_fate_won", "ranking_fate_died", "ranking_close",
        ]
        return {k: tr(f"ui.{k}") for k in keys}

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
            if request.args.get("token"):
                return _token_strip_redirect(
                    "index", "nhc_token", token,
                )
            pid = registry.player_id_for_hash(h)
            player = registry.get(pid)
            player_name = player["name"] if player else ""
            player_god = player.get("god_mode", False) if player else False
            player_lang = player.get("lang", "") if player else ""
            player_world = player.get("world", "hexcrawl") if player else "hexcrawl"
            player_difficulty = player.get("difficulty", "medium") if player else "medium"
            resp = make_response(render_template(
                "index.html", player_name=player_name,
                god_mode=player_god, player_lang=player_lang,
                player_world=player_world,
                player_difficulty=player_difficulty,
                welcome_labels=_welcome_labels(player_lang),
            ))
            _set_auth_cookie(resp, "nhc_token", token)
            return resp
        return render_template(
            "index.html",
            god_mode=config.god_mode,
            player_world="hexcrawl",
            player_difficulty="medium",
            welcome_labels=_welcome_labels(""),
        )

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({
            "status": "ok",
            "sessions": sessions.active_count,
        })

    @app.route("/api/tilesets", methods=["GET"])
    def tilesets():
        return jsonify(["classic"])

    # Hex overland tile art. The hextiles/ directory lives at the
    # project root; it's .gitignored (CC-licensed asset pack that's
    # too large to check in) and deployed to production manually via
    # scp. A runtime check at request time falls through to 404 if
    # the pack is missing so the hex client can render placeholder
    # glyphs instead of breaking.
    _HEXTILES_DIR = (
        Path(__file__).resolve().parents[2] / "hextiles"
    )

    @app.route("/hextiles/<path:relpath>", methods=["GET"])
    def hextile(relpath: str):
        if not _HEXTILES_DIR.is_dir():
            abort(404)
        return send_from_directory(
            _HEXTILES_DIR, relpath, max_age=60 * 60 * 24,
        )

    _HELP_LANGS = ("en", "es", "ca")

    @app.route("/api/help/<lang>", methods=["GET"])
    def help_text(lang: str):
        """Serve the help document for the given language.

        *lang* is restricted to the known locale codes so the path
        can never contain traversal segments or odd filesystem
        characters, even before the ``help_`` prefix.
        """
        if lang not in _HELP_LANGS:
            return "unsupported language", 400
        docs = Path(__file__).parent.parent.parent / "docs"
        path = docs / f"help_{lang}.md"
        if not path.exists():
            path = docs / "help_en.md"
        if not path.exists():
            return "Help not available.", 404
        return path.read_text(), 200, {"Content-Type": "text/plain"}

    # ── TTS routes ─────────────────────────────────────────

    @app.route("/api/tts/status", methods=["GET"])
    def tts_status():
        """Return TTS availability for the client."""
        engine = _get_tts_engine(app)
        return jsonify({"available": engine.is_available()})

    @app.route("/api/tts", methods=["POST"])
    @_player_auth
    def tts_synthesize():
        """Synthesize text to WAV audio.

        Requires a player token (piper is CPU-bound; exposing this
        unauthenticated lets any internet host pin server cores).
        The shared rate limiter caps sustained request rate per IP.
        """
        blocked = _check_rate_limit()
        if blocked:
            return blocked
        engine = _get_tts_engine(app)
        if not engine.is_available():
            return jsonify({"error": "TTS not available"}), 503

        data = request.get_json(silent=True) or {}
        text = data.get("text")
        lang = data.get("lang")
        if not text or not lang:
            return jsonify({"error": "text and lang required"}), 400

        try:
            wav_buf = engine.synthesize(text, lang)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 503

        return send_file(
            wav_buf,
            mimetype="audio/wav",
            download_name="tts.wav",
        )

    # ── Admin routes (LAN + admin token) ────────────────────

    @app.route("/admin")
    @_admin_auth
    def admin_page():
        from nhc.web.auth import _extract_token
        token = _extract_token(cookie_name="nhc_admin_token")
        if token and request.args.get("token"):
            return _token_strip_redirect(
                "admin_page", "nhc_admin_token", token,
            )
        resp = make_response(render_template(
            "admin.html", external_url=config.external_url,
        ))
        if token:
            _set_auth_cookie(resp, "nhc_admin_token", token)
        return resp

    @app.route("/api/admin/players", methods=["GET"])
    @_admin_auth
    def admin_list_players():
        if not registry:
            return jsonify([])
        now = time.time()
        players = registry.list_all()
        for p in players:
            # The admin UI never displays the raw token hash —
            # strip it before serializing so one more hop of
            # attacker reach (screenshot, cached JSON) doesn't
            # land on the full SHA-256.
            p.pop("token_hash", None)
            session = sessions.get_by_player(p["player_id"])
            p["online"] = session.connected if session else False
            p["has_session"] = session is not None
            if session is not None:
                p["session_started_at"] = session.created_at
                p["session_duration"] = max(
                    0, int(now - session.created_at),
                )
            else:
                p["session_started_at"] = None
                p["session_duration"] = None
            # ``last_seen`` is always present thanks to the
            # load-time default, but legacy rows without the key
            # must still serialize to a stable shape.
            p["last_seen"] = float(p.get("last_seen", 0.0))
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

    @app.route(
        "/api/admin/players/<player_id>/scores", methods=["DELETE"],
    )
    @_admin_auth
    def admin_clear_scores(player_id: str):
        leaderboard = app.config.get("LEADERBOARD")
        if not leaderboard:
            return jsonify({"error": "no leaderboard"}), 500
        removed = leaderboard.remove_player_entries(player_id)
        return jsonify({"status": "ok", "removed": removed})

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

    @app.route("/api/ranking", methods=["GET"])
    @_player_auth
    def ranking():
        """Return the top leaderboard entries.

        Requires a valid player token so nothing is exposed publicly.
        Accepts an optional ``?limit=N`` query parameter (1–50,
        default 10).
        """
        try:
            limit = int(request.args.get("limit", "10"))
        except ValueError:
            limit = 10
        limit = max(1, min(50, limit))
        entries = leaderboard.top(limit)
        return jsonify({
            "entries": [e.to_dict() for e in entries],
        })

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

        # Check for an active (disconnected) session. Either a
        # dungeon floor or a hex world counts as "has state" --
        # hex-mode games sit on an overland HexWorld while the
        # player is on the macro map, with ``game.level`` None
        # until they enter a feature.
        existing = sessions.get_by_player(pid)
        if existing and existing.game and (
            existing.game.level or existing.game.hex_world
        ):
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

        try:
            game.initialize(generate=True, executor=gen_pool)
        except Exception:
            logger.exception("Failed to restore game for player %s", pid)
            sessions.destroy(session.session_id)
            return jsonify({"error": "game restore failed"}), 500

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
                from nhc.rendering.level_svg import render_level_svg
                seed = game.seed or 0
                client.floor_svg = render_level_svg(
                    game.level, site=game._active_site,
                    seed=seed,
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
        # Optional world + difficulty selection. Default is
        # "hexcrawl"/"medium"; the welcome screen sends the
        # player's explicit choice when it differs.
        world_raw = data.get("world", "hexcrawl")
        difficulty_raw = data.get("difficulty", "medium")
        from nhc.hexcrawl.mode import Difficulty, GameMode, WorldType
        try:
            wtype = WorldType.from_str(world_raw)
        except ValueError:
            # Legacy fallback for old clients
            try:
                world_mode = GameMode.from_str(world_raw)
            except ValueError:
                return jsonify({
                    "error": f"unknown world: {world_raw!r}",
                }), 400
        else:
            try:
                diff = Difficulty.from_str(difficulty_raw)
            except ValueError:
                return jsonify({
                    "error": f"unknown difficulty: {difficulty_raw!r}",
                }), 400
            world_mode = GameMode.from_world_difficulty(wtype, diff)
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

        # Pre-delete the autosave BEFORE constructing the Game so
        # a concurrent autosave from the old (still-running) game
        # loop can't race with the delete inside Game.initialize.
        # Without this, the old WebSocket handler's last hex-step
        # autosave can land between the session.destroy above and
        # the Game.initialize delete, leaving stale exploration
        # state that the new game accidentally restores.
        if reset and save_dir:
            from nhc.core.autosave import delete_autosave
            delete_autosave(save_dir)
            logger.info(
                "Pre-deleted autosave for player %s (reset=True)",
                pid or "anonymous",
            )

        logger.info("Creating new game: lang=%s tileset=%s reset=%s "
                     "player=%s", lang, tileset, reset,
                     pid or "anonymous")
        try:
            session = sessions.create(
                lang=lang, tileset=tileset,
                player_id=pid, save_dir=save_dir,
            )
        except ValueError as exc:
            logger.warning("Session limit: %s", exc)
            return jsonify({"error": str(exc)}), 429

        # Persist language and game preferences for returning players
        if registry and pid and session.lang:
            registry.set_lang(pid, session.lang)
        if registry and pid:
            registry.set_preferences(
                pid,
                world_mode.world_type.value,
                world_mode.difficulty.value,
            )

        # Initialize i18n and create the game instance
        from nhc.i18n import init as i18n_init
        i18n_init(session.lang)

        from nhc.core.game import Game
        from nhc.rendering.web_client import WebClient

        client = WebClient(game_mode="classic", lang=session.lang)
        backend = _create_llm_backend()
        logger.debug("LLM backend: %s", type(backend).__name__
                      if backend else "None")

        # God mode: the server's global --god flag forces it on for
        # everyone; otherwise check the per-player flag in the
        # registry (set via admin panel).
        player_god = config.god_mode
        if not player_god and registry and pid:
            pdata = registry.get(pid)
            if pdata:
                player_god = pdata.get("god_mode", False)
        game = Game(
            client=client,
            backend=backend,
            game_mode="classic",
            world_mode=world_mode,
            reset=reset,
            shape_variety=config.shape_variety,
            god_mode=player_god,
            save_dir=session.save_dir,
        )
        session.game = game

        # Initialize the game world. Hex modes skip the dungeon
        # generation path entirely (handled inside Game.initialize)
        # and route the pool-free hex-world setup. Dungeon mode
        # keeps the existing pool-offloaded generation so the
        # server stays responsive and multiple cores serve
        # concurrent players.
        logger.info(
            "Initialising session %s (world_mode=%s)...",
            session.session_id, world_mode.value,
        )
        try:
            if world_mode.is_hex:
                game.initialize()
            else:
                game.initialize(generate=True, executor=gen_pool)
        except Exception:
            logger.exception("Failed to initialize game")
            sessions.destroy(session.session_id)
            return jsonify({"error": "game initialization failed"}), 500

        if game.level is not None:
            logger.info("Dungeon generated: %dx%d, %d rooms",
                         game.level.width, game.level.height,
                         len(game.level.rooms))
        else:
            logger.info(
                "Hex world ready: %d cells, start hex (%d,%d)",
                len(game.hex_world.cells),
                game.hex_player_position.q,
                game.hex_player_position.r,
            )

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
            # Only use disk-cached SVG when resuming, not on reset
            cached = (load_svg_cache(session.save_dir)
                      if not reset else None)
            if cached:
                client.floor_svg = cached[0]
                client.floor_svg_id = _uuid.uuid4().hex[:12]
                logger.info("Floor SVG from disk cache: %d bytes",
                            len(client.floor_svg))
            elif game.level:
                from nhc.rendering.level_svg import render_level_svg
                logger.info("Rendering floor SVG...")
                seed = game.seed or 0
                client.floor_svg = render_level_svg(
                    game.level, site=game._active_site,
                    seed=seed,
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
        resp = jsonify(client._gather_debug_data(
            session.game.level, session.game.world))
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    @app.route("/api/game/<session_id>/labels.json", methods=["GET"])
    @_player_auth
    def game_labels(session_id: str):
        session = sessions.get(session_id)
        if not session:
            return jsonify({"error": "session not found"}), 404
        # Initialize i18n for the current worker thread before
        # resolving labels. Under the gthread worker this request may
        # land on any pool thread, and the previous gevent-era
        # assumption that a single shared thread-local manager was
        # set up once by /api/game/new no longer holds — an
        # uninitialized manager returns the raw key for every lookup.
        from nhc.i18n import init as i18n_init
        i18n_init(session.lang)
        client = session.game.renderer
        resp = jsonify(client._ui_labels())
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
        # Look up the SVG by the UUID baked into the URL. The
        # current-floor shortcut (client.floor_svg) is racy: when
        # the player bounces in and out of a building, the HTTP
        # GET can arrive after the engine has already swapped
        # client.floor_svg to the next level, serving the wrong
        # body under a Cache-Control response that the browser
        # will then reuse forever. Iterating the svg_cache keeps
        # the URL contract honest -- the SVG with id X always
        # returns the SVG registered as id X.
        svg_body: str | None = None
        svg_cache = getattr(session.game, "_svg_cache", None)
        if svg_cache:
            for cached_id, cached_svg in svg_cache.values():
                if cached_id == svg_id:
                    svg_body = cached_svg
                    break
        if svg_body is None and client.floor_svg_id == svg_id:
            svg_body = client.floor_svg
        if svg_body is None:
            return "floor SVG not found", 404
        resp = make_response(svg_body)
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

    # ─────────────────────────────────────────────────────────────
    # Hex-debug endpoints (in-game, gated on god_mode). Called by
    # the Hex tab of the floating debug window.
    # ─────────────────────────────────────────────────────────────

    def _require_hex_debug_session(session_id: str):
        """Resolve a god-mode session with a live HexWorld.

        Returns ``(session, None)`` on success or
        ``(None, (body, status))`` on failure so the caller can
        ``return jsonify(body), status``.
        """
        session = sessions.get(session_id)
        if session is None or session.game is None:
            return None, ({"error": "not available"}, 404)
        if not session.game.god_mode:
            return None, ({"error": "not available"}, 404)
        hw = getattr(session.game, "hex_world", None)
        if hw is None:
            return None, (
                {"error": "session is not in hex mode"}, 400,
            )
        return session, None

    @app.route(
        "/api/game/<session_id>/hex/state", methods=["GET"],
    )
    @_player_auth
    def game_hex_state(session_id: str):
        from nhc.hexcrawl.coords import HexCoord
        from nhc.hexcrawl.debug import show_world_state
        session, err = _require_hex_debug_session(session_id)
        if err is not None:
            body, status = err
            return jsonify(body), status
        player = session.game.hex_player_position or HexCoord(0, 0)
        return jsonify(show_world_state(session.game.hex_world, player))

    @app.route(
        "/api/game/<session_id>/hex/reveal", methods=["POST"],
    )
    @_player_auth
    def game_hex_reveal(session_id: str):
        from nhc.hexcrawl.debug import reveal_all_hexes
        session, err = _require_hex_debug_session(session_id)
        if err is not None:
            body, status = err
            return jsonify(body), status
        hw = session.game.hex_world
        n = reveal_all_hexes(hw)
        return jsonify({
            "newly_revealed": n,
            "total_revealed": len(hw.revealed),
            "total_cells": len(hw.cells),
        })

    @app.route(
        "/api/game/<session_id>/hex/teleport", methods=["POST"],
    )
    @_player_auth
    def game_hex_teleport(session_id: str):
        from nhc.hexcrawl.coords import HexCoord
        from nhc.hexcrawl.debug import teleport_hex
        session, err = _require_hex_debug_session(session_id)
        if err is not None:
            body, status = err
            return jsonify(body), status
        data = request.get_json(silent=True) or {}
        try:
            target = HexCoord(q=int(data["q"]), r=int(data["r"]))
        except (KeyError, TypeError, ValueError):
            return jsonify({"error": "payload must be {q, r}"}), 400
        ok = teleport_hex(session.game.hex_world, target)
        if ok:
            session.game.hex_player_position = target
        return jsonify({
            "ok": ok,
            "target": {"q": target.q, "r": target.r},
        })

    @app.route(
        "/api/game/<session_id>/hex/force_encounter", methods=["POST"],
    )
    @_player_auth
    def game_hex_force_encounter(session_id: str):
        from nhc.hexcrawl.debug import force_encounter
        from nhc.hexcrawl.model import Biome
        session, err = _require_hex_debug_session(session_id)
        if err is not None:
            body, status = err
            return jsonify(body), status
        data = request.get_json(silent=True) or {}
        biome_str = data.get("biome")
        if not biome_str:
            return jsonify({"error": "biome is required"}), 400
        try:
            biome = Biome(biome_str)
        except ValueError:
            return jsonify({"error": f"unknown biome {biome_str!r}"}), 400
        creatures = data.get("creatures")
        enc = force_encounter(biome, creatures=creatures)
        session.game.pending_encounter = enc
        return jsonify({
            "biome": enc.biome.value,
            "creatures": list(enc.creatures),
        })

    @app.route(
        "/api/game/<session_id>/hex/advance_clock", methods=["POST"],
    )
    @_player_auth
    def game_hex_advance_clock(session_id: str):
        from nhc.hexcrawl.debug import advance_day_clock
        session, err = _require_hex_debug_session(session_id)
        if err is not None:
            body, status = err
            return jsonify(body), status
        data = request.get_json(silent=True) or {}
        try:
            segments = int(data["segments"])
        except (KeyError, TypeError, ValueError):
            return jsonify({"error": "segments is required"}), 400
        try:
            advance_day_clock(session.game.hex_world, segments)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        hw = session.game.hex_world
        return jsonify({"day": hw.day, "time": hw.time.name.lower()})

    @app.route(
        "/api/game/<session_id>/hex/rumor_truth", methods=["POST"],
    )
    @_player_auth
    def game_hex_rumor_truth(session_id: str):
        from nhc.hexcrawl.debug import set_rumor_truth
        session, err = _require_hex_debug_session(session_id)
        if err is not None:
            body, status = err
            return jsonify(body), status
        data = request.get_json(silent=True) or {}
        rumor_id = data.get("rumor_id")
        truth = data.get("truth")
        if rumor_id is None or truth is None:
            return jsonify(
                {"error": "rumor_id and truth are required"},
            ), 400
        updated = set_rumor_truth(
            session.game.hex_world, str(rumor_id), bool(truth),
        )
        return jsonify({
            "rumor_id": rumor_id,
            "truth": bool(truth),
            "updated": updated,
        })

    @app.route(
        "/api/game/<session_id>/hex/clear_dungeon", methods=["POST"],
    )
    @_player_auth
    def game_hex_clear_dungeon(session_id: str):
        from nhc.hexcrawl.coords import HexCoord
        from nhc.hexcrawl.debug import clear_dungeon_at
        session, err = _require_hex_debug_session(session_id)
        if err is not None:
            body, status = err
            return jsonify(body), status
        data = request.get_json(silent=True) or {}
        try:
            coord = HexCoord(q=int(data["q"]), r=int(data["r"]))
        except (KeyError, TypeError, ValueError):
            return jsonify({"error": "payload must be {q, r}"}), 400
        ok = clear_dungeon_at(session.game.hex_world, coord)
        return jsonify({
            "ok": ok,
            "coord": {"q": coord.q, "r": coord.r},
            "cleared_count": len(session.game.hex_world.cleared),
        })

    @app.route(
        "/api/game/<session_id>/hex/seed_dungeon", methods=["POST"],
    )
    @_player_auth
    def game_hex_seed_dungeon(session_id: str):
        from nhc.hexcrawl.coords import HexCoord
        from nhc.hexcrawl.debug import seed_dungeon_at
        from nhc.hexcrawl.model import HexFeatureType
        session, err = _require_hex_debug_session(session_id)
        if err is not None:
            body, status = err
            return jsonify(body), status
        data = request.get_json(silent=True) or {}
        try:
            coord = HexCoord(q=int(data["q"]), r=int(data["r"]))
            feature = HexFeatureType(data["feature"])
            template = str(data["template"])
        except (KeyError, TypeError, ValueError) as exc:
            return jsonify(
                {"error": f"bad payload: {exc}"},
            ), 400
        depth = int(data.get("depth") or 1)
        ok = seed_dungeon_at(
            session.game.hex_world, coord,
            feature=feature, template=template, depth=depth,
        )
        return jsonify({
            "ok": ok,
            "coord": {"q": coord.q, "r": coord.r},
            "feature": feature.value,
            "template": template,
            "depth": depth,
        })

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

    @app.route("/api/game/<session_id>/henchmen", methods=["GET"])
    @_player_auth
    def game_henchmen(session_id: str):
        """Return character sheets for hired henchmen (god mode)."""
        session = sessions.get(session_id)
        if not session or not session.game.god_mode:
            return jsonify({"error": "not available"}), 404
        from nhc.core.save import _serialize_entities
        from nhc.debug_tools.tools.game_state import (
            build_henchman_sheets,
        )
        game = session.game
        ecs = _serialize_entities(game.world)
        result = build_henchman_sheets(
            ecs, hired_only=True, owner_id=game.player_id,
        )
        return jsonify(result)

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
            "debug": client._gather_debug_data(level, game.world),
        }
        out = Path("debug/exports")
        out.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = out / f"layer_state_{ts}.json"
        path.write_text(_json.dumps(data, indent=2))
        logger.info("Exported layer state: %s", path)
        return jsonify({"path": str(path)})

    @app.route("/api/game/<session_id>/export/hatch_debug",
               methods=["POST"])
    @_player_auth
    def export_hatch_debug(session_id: str):
        session = sessions.get(session_id)
        if not session or not session.game.god_mode:
            return jsonify({"error": "not available"}), 404
        import json as _json
        from datetime import datetime
        game = session.game
        client = game.renderer
        data = {
            "timestamp": datetime.now().isoformat(),
            "turn": game.turn,
            **client._gather_hatch_debug(game.level),
        }
        out = Path("debug/exports")
        out.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = out / f"hatch_debug_{ts}.json"
        path.write_text(_json.dumps(data, indent=2))
        logger.info("Exported hatch debug: %s", path)
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

    @app.route(
        "/api/game/<session_id>/capture_layers", methods=["POST"],
    )
    @_player_auth
    def capture_layers(session_id: str):
        """Ask the browser to capture canvas layer PNGs.

        Sends a ``capture_layers`` WebSocket message to the client.
        The client captures all canvases and POSTs them back to
        ``/export/layer_pngs``. The caller should wait ~2 seconds
        before downloading the bundle.
        """
        session = sessions.get(session_id)
        if not session or not session.game.god_mode:
            return jsonify({"error": "not available"}), 404
        client = session.game.renderer
        client._send({"type": "capture_layers"})
        return jsonify({"status": "ok", "message": "capture requested"})

    @app.route(
        "/api/game/<session_id>/export/layer_pngs", methods=["POST"],
    )
    @_player_auth
    def upload_layer_pngs(session_id: str):
        """Receive base64-encoded layer PNGs from the client.

        Stashed on the session so the next bundle download includes
        them. Payload: ``{"layers": {"name": "data:image/png;base64,..."}}``.
        """
        session = sessions.get(session_id)
        if not session or not session.game.god_mode:
            return jsonify({"error": "not available"}), 404
        data = request.get_json(silent=True) or {}
        session.layer_pngs = data.get("layers", {})
        session.console_log = data.get("console_log", "")
        return jsonify({"status": "ok", "count": len(session.layer_pngs)})

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
            level = game.level
            static, dynamic = client._gather_stats(
                game.world, game.player_id, game.turn, level)
            gen_params = (game.generation_params.to_dict()
                          if game.generation_params else None)
            state = {
                "timestamp": datetime.now().isoformat(),
                "turn": game.turn,
                "player_id": game.player_id,
                "seed": game.seed,
                "level_id": level.id if level else None,
                "floor_svg_id": client.floor_svg_id,
                "generation_params": gen_params,
                "stats": {**static, **dynamic},
                "ecs": _serialize_entities(game.world),
            }
            if level:
                state["entities"] = client._gather_entities(
                    game.world, level, game.player_id)
                state["level"] = _serialize_level(level)
            # Hex world state (when in hexcrawl mode).
            hex_world = getattr(game, "hex_world", None)
            if hex_world:
                from nhc.core.save import _serialize_hex_world
                state["hex_world"] = _serialize_hex_world(hex_world)
                state["hex_player"] = (
                    {"q": game.hex_player_position.q,
                     "r": game.hex_player_position.r}
                    if game.hex_player_position else None
                )
            _add_text(tar, f"exports/game_state_{ts}.json",
                      _json.dumps(state, indent=2))

            # 2. Layer state JSON (dungeon mode only)
            if level:
                explored = [[x, y]
                            for y in range(level.height)
                            for x in range(level.width)
                            if (t := level.tile_at(x, y))
                            and t.explored]
                layer = {
                    "timestamp": datetime.now().isoformat(),
                    "turn": game.turn,
                    "fov": client._gather_fov(level),
                    "explored": explored,
                    "doors": client._gather_doors(level),
                    "debug": client._gather_debug_data(
                        level, game.world),
                }
                _add_text(tar, f"exports/layer_state_{ts}.json",
                          _json.dumps(layer, indent=2))

                # 2b. Hatch polygon debug snapshot.
                hatch = {
                    "timestamp": datetime.now().isoformat(),
                    "turn": game.turn,
                    **client._gather_hatch_debug(level),
                }
                _add_text(tar, f"exports/hatch_debug_{ts}.json",
                          _json.dumps(hatch, indent=2))

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

            # 7. Layer PNGs (uploaded by the client before bundle
            # download). Each value is a data:image/png;base64 URI.
            import base64
            layer_pngs = getattr(session, "layer_pngs", {})
            for name, data_uri in layer_pngs.items():
                try:
                    # Strip the data:image/png;base64, prefix.
                    _, encoded = data_uri.split(",", 1)
                    png_bytes = base64.b64decode(encoded)
                    info = tarfile.TarInfo(
                        name=f"layers/{name}.png",
                    )
                    info.size = len(png_bytes)
                    tar.addfile(info, io.BytesIO(png_bytes))
                except Exception:
                    pass  # skip malformed entries
            # Clear after bundling so they don't accumulate.
            session.layer_pngs = {}

            # 8. Browser console log (captured by the client-side
            # interceptor and uploaded with layer PNGs).
            console_log = getattr(session, "console_log", "")
            if console_log:
                _add_text(tar, "console.log", console_log)
                session.console_log = ""

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

    cidrs_env = os.environ.get("NHC_ADMIN_LAN_CIDRS", "")
    admin_lan_cidrs = [c.strip() for c in cidrs_env.split(",")
                       if c.strip()]

    config = WebConfig(
        host="0.0.0.0",
        port=int(os.environ.get("NHC_PORT", "8080")),
        max_sessions=int(os.environ.get("NHC_MAX_SESSIONS", "8")),
        data_dir=data_dir,
        auth_required=bool(os.environ.get("NHC_AUTH_TOKEN")),
        god_mode=False,
        hatch_distance=float(os.environ.get("NHC_HATCH_DISTANCE", "1.0")),
        external_url=os.environ.get("NHC_EXTERNAL_URL", ""),
        admin_lan_cidrs=admin_lan_cidrs,
        # gunicorn in production always sits behind Caddy on
        # loopback — trust one forwarded hop so the LAN allowlist
        # sees the real client IP.
        trust_proxy=True,
    )
    auth_token = os.environ.get("NHC_AUTH_TOKEN")
    return create_app(config, auth_token=auth_token)
