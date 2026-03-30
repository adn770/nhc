"""WebSocket handler for game sessions.

Each WebSocket connection is tied to a game session. The handler
runs the game loop in a background thread while the WS connection
relays messages between the Game (via WebClient) and the browser.
"""

from __future__ import annotations

import asyncio
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
        logger.info("WS attached to game, sending floor SVG...")

        # Send the floor SVG now that WS is connected
        if client.floor_svg:
            logger.info("Sending floor SVG: %d bytes",
                        len(client.floor_svg))
            client._send({"type": "floor", "svg": client.floor_svg})
        else:
            logger.warning("No floor SVG to send!")

        # Send initial game state
        if session.game.level:
            entities = client._gather_entities(
                session.game.world, session.game.level)
            fov = client._gather_fov(session.game.level)
            logger.info("Sending initial state: %d entities, %d fov tiles",
                        len(entities), len(fov))
            client._send({
                "type": "state",
                "entities": entities,
                "fov": fov,
                "turn": session.game.turn,
            })

        # Run the game loop in a thread so the WS stays responsive
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

        game_thread = threading.Thread(
            target=_run_game, daemon=True,
        )
        game_thread.start()

        # Keep the WS connection alive while the game runs.
        # flask-sock closes the WS when this function returns.
        game_thread.join()

        logger.info("WS disconnected: session=%s", session_id)
        # Clean up
        sessions.destroy(session_id)
