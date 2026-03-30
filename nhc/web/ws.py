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

from flask_sock import Sock

from nhc.web.sessions import SessionManager

logger = logging.getLogger(__name__)


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

        client = session.game.renderer
        client.set_ws(ws)
        logger.info("WS attached to game")

        # Send the floor SVG now that WS is connected
        if client.floor_svg:
            logger.info("Sending floor SVG: %d bytes",
                        len(client.floor_svg))
            ws.send(json.dumps({"type": "floor", "svg": client.floor_svg}))
        else:
            logger.warning("No floor SVG to send!")

        # Send initial game state
        if session.game.level:
            entities = client._gather_entities(
                session.game.world, session.game.level)
            fov = client._gather_fov(session.game.level)
            logger.info("Sending initial state: %d entities, %d fov tiles",
                        len(entities), len(fov))
            ws.send(json.dumps({
                "type": "state",
                "entities": entities,
                "fov": fov,
                "turn": session.game.turn,
            }))

        # Sender thread: drains client output queue → WS
        stop_event = threading.Event()

        def _sender():
            while not stop_event.is_set():
                try:
                    data = client._out_queue.get(timeout=0.1)
                    ws.send(data)
                except Exception:
                    pass  # queue.Empty or WS error

        sender_thread = threading.Thread(target=_sender, daemon=True)
        sender_thread.start()

        # Game loop thread
        def _run_game():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                logger.info("Game loop starting for session %s",
                            session_id)
                loop.run_until_complete(session.game.run())
                logger.info("Game loop ended for session %s",
                            session_id)
            except Exception:
                logger.exception("Game loop error for session %s",
                                 session_id)
            finally:
                loop.close()
                stop_event.set()

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

        # Cleanup
        stop_event.set()
        game_thread.join(timeout=5)
        sender_thread.join(timeout=2)
        logger.info("WS disconnected: session=%s", session_id)
        sessions.destroy(session_id)
