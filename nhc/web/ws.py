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
        sessions: SessionManager = app.config["SESSIONS"]
        session = sessions.get(session_id)
        if not session:
            ws.send('{"type":"error","text":"session not found"}')
            return

        if not session.game:
            ws.send('{"type":"error","text":"game not initialized"}')
            return

        client = session.game.renderer
        client.set_ws(ws)

        # Run the game loop in a thread so the WS stays responsive
        def _run_game():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(session.game.run())
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

        # Clean up
        sessions.destroy(session_id)
