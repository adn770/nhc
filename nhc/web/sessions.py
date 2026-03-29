"""Game session manager.

Manages multiple concurrent solo game instances, each with its own
World, Level, and LLM context.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from nhc.web.config import WebConfig


@dataclass
class Session:
    """A single game session."""

    session_id: str
    lang: str
    tileset: str
    created_at: float = field(default_factory=time.time)
    game: Any = None  # Game instance, set after creation


class SessionManager:
    """Manages concurrent game sessions."""

    def __init__(self, config: WebConfig) -> None:
        self._config = config
        self._sessions: dict[str, Session] = {}

    @property
    def active_count(self) -> int:
        return len(self._sessions)

    def create(
        self, lang: str = "", tileset: str = "",
    ) -> Session:
        """Create a new game session.

        Raises ValueError if the session limit is reached.
        """
        if len(self._sessions) >= self._config.max_sessions:
            raise ValueError(
                f"Session limit reached ({self._config.max_sessions})"
            )
        sid = secrets.token_urlsafe(16)
        session = Session(
            session_id=sid,
            lang=lang or self._config.default_lang,
            tileset=tileset or self._config.default_tileset,
        )
        self._sessions[sid] = session
        return session

    def get(self, session_id: str) -> Session | None:
        """Retrieve a session by ID."""
        return self._sessions.get(session_id)

    def destroy(self, session_id: str) -> bool:
        """Remove a session. Returns True if it existed."""
        return self._sessions.pop(session_id, None) is not None

    def list_sessions(self) -> list[dict[str, Any]]:
        """Return summary info for all active sessions."""
        return [
            {
                "session_id": s.session_id,
                "lang": s.lang,
                "tileset": s.tileset,
                "created_at": s.created_at,
            }
            for s in self._sessions.values()
        ]
