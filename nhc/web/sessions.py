"""Game session manager.

Manages multiple concurrent solo game instances, each with its own
World, Level, and LLM context.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nhc.web.config import WebConfig

logger = logging.getLogger(__name__)

_REAPER_TIMEOUT = 30 * 60  # 30 minutes


def player_id_from_token(token: str) -> str:
    """Derive a stable player_id from a player token."""
    return hashlib.sha256(token.encode()).hexdigest()[:12]


@dataclass
class Session:
    """A single game session."""

    session_id: str
    lang: str
    tileset: str
    created_at: float = field(default_factory=time.time)
    game: Any = None  # Game instance, set after creation
    player_id: str = ""
    save_dir: Path | None = None
    connected: bool = True
    disconnected_at: float | None = None


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
        player_id: str = "", save_dir: Path | None = None,
    ) -> Session:
        """Create a new game session.

        Raises ValueError if the session limit is reached.
        """
        self._reap_stale()
        if len(self._sessions) >= self._config.max_sessions:
            raise ValueError(
                f"Session limit reached ({self._config.max_sessions})"
            )
        sid = secrets.token_urlsafe(16)
        session = Session(
            session_id=sid,
            lang=lang or self._config.default_lang,
            tileset=tileset or self._config.default_tileset,
            player_id=player_id,
            save_dir=save_dir,
        )
        self._sessions[sid] = session
        return session

    def get(self, session_id: str) -> Session | None:
        """Retrieve a session by ID."""
        return self._sessions.get(session_id)

    def get_by_player(self, player_id: str) -> Session | None:
        """Find an active session for a player."""
        for s in self._sessions.values():
            if s.player_id == player_id:
                return s
        return None

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
                "player_id": s.player_id,
                "connected": s.connected,
            }
            for s in self._sessions.values()
        ]

    def _reap_stale(self) -> None:
        """Destroy sessions disconnected longer than the timeout."""
        now = time.time()
        stale = [
            sid for sid, s in self._sessions.items()
            if not s.connected
            and s.disconnected_at is not None
            and (now - s.disconnected_at) > _REAPER_TIMEOUT
        ]
        for sid in stale:
            logger.info("Reaping stale session %s", sid)
            self._sessions.pop(sid, None)
