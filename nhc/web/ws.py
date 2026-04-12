"""WebSocket handler for game sessions.

Each WebSocket connection is tied to a game session. The WS handler
thread owns the socket — it reads incoming messages into the client's
input queue, and a sender thread drains the output queue to the socket.
The game loop runs in its own thread, communicating via queues.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time

from flask import request
from flask_sock import Sock

from nhc.web.sessions import SessionManager

logger = logging.getLogger(__name__)


def _submit_final_score(session) -> None:
    """Record the run in the leaderboard, if one is configured.

    Called when a game session ends (death or victory).  Idempotent
    via ``session.score_submitted`` so races between the WS ack
    interceptor and the session-teardown path never double-count.
    Errors are logged but never raised — leaderboard bookkeeping
    must never block session teardown.
    """
    if getattr(session, "score_submitted", False):
        return
    try:
        from flask import current_app
        leaderboard = current_app.config.get("LEADERBOARD")
        if not leaderboard:
            return
        registry = current_app.config.get("PLAYER_REGISTRY")
        game = session.game
        if not game or not game.level:
            return
        if game.god_mode:
            logger.info("Skipping leaderboard for god-mode game")
            return
        player = game.world.get_component(game.player_id, "Player")
        xp = player.xp if player else 0
        gold = player.gold if player else 0
        depth = game.level.depth if game.level else 1
        won = bool(game.won)
        # Look up the player's display name from the registry;
        # fall back to a truncated player_id for anonymous runs.
        name = ""
        if registry and session.player_id:
            pdata = registry.get(session.player_id)
            if pdata:
                name = pdata.get("name", "")
        if not name:
            name = session.player_id[:8] or "anonymous"

        from nhc.web.leaderboard import (
            LeaderboardEntry,
            compute_score,
        )
        entry = LeaderboardEntry(
            player_id=session.player_id or "",
            name=name,
            score=compute_score(xp=xp, gold=gold, depth=depth, won=won),
            depth=depth,
            turn=game.turn,
            won=won,
            killed_by=game.killed_by or "",
            timestamp=time.time(),
        )
        leaderboard.submit(entry)
        session.score_submitted = True
    except Exception:
        logger.exception("Failed to submit leaderboard score")


def _send_floor_state(ws, session, client, base_url: str) -> None:
    """Send floor/entity/fov state to a newly connected WebSocket."""
    game = session.game
    if client.floor_svg and game.level:
        entities = client._gather_entities(
            game.world, game.level, game.player_id)
        fov = client._gather_fov(game.level)
        doors = client._gather_doors(game.level)
        walk = client._gather_walk(game.level)
        explored = client._gather_explored(game.level)
        logger.info("Sending floor init: floor=%d bytes, "
                    "%d entities, %d doors, %d fov tiles",
                    len(client.floor_svg),
                    len(entities), len(doors), len(fov))
        ws.send(json.dumps({
            "type": "floor",
            "floor_url": f"{base_url}/floor/{client.floor_svg_id}.svg",
            "hatch_url": "/api/hatch.svg",
            "entities": entities,
            "doors": doors,
            "fov": fov,
            "walk": walk,
            "explored": explored,
            "turn": game.turn,
        }))
    elif client.floor_svg:
        logger.info("Sending floor init (no level state)")
        ws.send(json.dumps({
            "type": "floor",
            "floor_url": f"{base_url}/floor.svg",
            "hatch_url": f"{base_url}/hatch.svg",
        }))
    else:
        logger.warning("No floor SVG to send!")

    if game.god_mode and game.level:
        ws.send(json.dumps({
            "type": "debug_url",
            "url": f"{base_url}/debug.json",
        }))
        logger.info("Sent debug_url for god mode")


def _run_ws_session(
    ws, session, sessions: SessionManager, session_id: str,
    start_game_loop: bool = True,
) -> None:
    """Drive the WS message loop, sender thread, and game thread."""
    client = session.game.renderer
    sid = session.session_id
    base_url = f"/api/game/{sid}"
    client.set_ws(ws, base_url=base_url)
    logger.info("WS attached to game (reconnect=%s)",
                not start_game_loop)

    session.connected = True
    session.disconnected_at = None

    _send_floor_state(ws, session, client, base_url)

    # Sender thread: drains client output queue → WS
    stop_event = threading.Event()

    def _sender():
        while not stop_event.is_set():
            try:
                data = client._out_queue.get(timeout=0.1)
                ws.send(data)
            except Exception:
                pass  # queue.Empty or WS error
        # Drain remaining messages (e.g. game_over)
        while not client._out_queue.empty():
            try:
                data = client._out_queue.get_nowait()
                ws.send(data)
            except Exception:
                break

    sender_thread = threading.Thread(target=_sender, daemon=True)
    sender_thread.start()

    game_thread = None
    if start_game_loop:
        def _run_game():
            # Initialize thread-local state — each game thread
            # needs its own i18n and RNG so concurrent sessions
            # don't interfere.
            from nhc.i18n import init as i18n_init
            i18n_init(session.lang)

            from nhc.utils.rng import set_seed
            if session.game and session.game.seed is not None:
                set_seed(session.game.seed)

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                logger.info("Game loop starting for session %s",
                            session_id)
                loop.run_until_complete(session.game.run())
                logger.info("Game loop ended for session %s "
                            "(game_over=%s, won=%s, turn=%d)",
                            session_id, session.game.game_over,
                            session.game.won, session.game.turn)
            except Exception:
                logger.exception("Game loop error for session %s",
                                 session_id)
            finally:
                loop.close()
                stop_event.set()
                logger.info("Game thread cleanup done for session %s",
                            session_id)

        game_thread = threading.Thread(target=_run_game, daemon=True)
        game_thread.start()

    # This thread (WS handler) reads incoming messages → input queue
    try:
        while not stop_event.is_set():
            try:
                raw = ws.receive(timeout=1)
                if raw:
                    logger.debug("WS RECV: %s", raw[:120])
                    # Submit the leaderboard score the instant the
                    # client acknowledges the game-over modal.  The
                    # death modal fetches /api/ranking a moment
                    # later, so the entry must already be on disk.
                    try:
                        parsed = json.loads(raw)
                        if (isinstance(parsed, dict)
                                and parsed.get("type") == "game_over_ack"):
                            _submit_final_score(session)
                    except Exception:
                        pass
                    client._in_queue.put(raw)
            except Exception:
                break
    except Exception:
        logger.debug("WS receive loop ended")

    # WS disconnected — inject disconnect sentinel into input queue
    client._in_queue.put({"type": "disconnect"})
    stop_event.set()

    if game_thread:
        logger.info("WS cleanup: joining game thread for session %s",
                     session_id)
        game_thread.join(timeout=5)
        if game_thread.is_alive():
            logger.warning("Game thread still alive after 5s for %s",
                           session_id)
    sender_thread.join(timeout=2)

    game = session.game
    if game.game_over or game.won:
        logger.info("WS disconnect: game ended, destroying session %s",
                     session_id)
        _submit_final_score(session)
        sessions.destroy(session_id)
    else:
        session.connected = False
        session.disconnected_at = time.time()
        logger.info("WS disconnect: session %s suspended "
                     "(player=%s, turn=%d)",
                     session_id, session.player_id, game.turn)


def register_ws(app, sock: Sock) -> None:
    """Register WebSocket routes on the Flask app."""

    @sock.route("/ws/game/<session_id>")
    def game_ws(ws, session_id: str):
        """Handle a WebSocket connection for a game session."""
        logger.info("WS connect: session=%s", session_id)

        # Validate player token when auth is enabled
        config = app.config.get("NHC_CONFIG")
        registry = app.config.get("PLAYER_REGISTRY")
        if config and config.auth_required and registry:
            from nhc.web.auth import hash_token
            token = request.args.get("token")
            if not token or not registry.is_valid_token_hash(
                    hash_token(token)):
                ws.send('{"type":"error","text":"authentication required"}')
                return

        sessions: SessionManager = app.config["SESSIONS"]
        session = sessions.get(session_id)
        if not session:
            logger.warning("WS session not found: %s", session_id)
            ws.send('{"type":"error","text":"session not found"}')
            return

        if not session.game:
            logger.warning("WS game not initialized: %s", session_id)
            ws.send('{"type":"error","text":"game not initialized"}')
            return

        # Reconnecting to a suspended session
        if not session.connected and session.game.level:
            logger.info("Resuming suspended session %s", session_id)
            session.game.running = True
            _run_ws_session(ws, session, sessions, session_id,
                            start_game_loop=True)
            return

        _run_ws_session(ws, session, sessions, session_id,
                        start_game_loop=True)
