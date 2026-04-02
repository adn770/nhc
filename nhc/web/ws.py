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

from flask_sock import Sock

from nhc.web.sessions import SessionManager

logger = logging.getLogger(__name__)


def _send_floor_state(ws, session, client, base_url: str) -> None:
    """Send floor/entity/fov state to a newly connected WebSocket."""
    game = session.game
    if client.floor_svg and game.level:
        entities = client._gather_entities(
            game.world, game.level, game.player_id)
        fov = client._gather_fov(game.level)
        doors = client._gather_doors(game.level)
        hatch_clear = client._gather_hatch_clear(game.level)
        logger.info("Sending floor init: floor=%d bytes, "
                    "hatch=%d bytes (via HTTP), "
                    "%d entities, %d doors, %d fov tiles",
                    len(client.floor_svg),
                    len(client.hatch_svg) if client.hatch_svg else 0,
                    len(entities), len(doors), len(fov))
        ws.send(json.dumps({
            "type": "floor",
            "floor_url": f"{base_url}/floor.svg",
            "hatch_url": f"{base_url}/hatch.svg",
            "entities": entities,
            "doors": doors,
            "fov": fov,
            "hatch_clear": hatch_clear,
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
