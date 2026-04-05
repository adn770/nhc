"""Persistent player registry backed by a JSON file.

Stores player accounts (name, token hash, revocation status) at
``{data_dir}/players.json``.  Thread-safe for in-process access
via a lock; atomic writes via tmp + os.replace prevent corruption.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path

from nhc.web.auth import generate_token, hash_token
from nhc.web.sessions import player_id_from_token

logger = logging.getLogger(__name__)


# Minimum interval between ``last_seen`` disk writes per player.
# The in-memory value is always updated; persistence is throttled
# so hot code paths (every authenticated request) do not hammer
# the registry file.
_TOUCH_PERSIST_INTERVAL = 60.0


class PlayerRegistry:
    """Manage registered players on disk."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._players: list[dict] = []
        self._lock = threading.Lock()

    # ── Persistence ─────────────────────────────────────────

    def load(self) -> None:
        """Read player data from disk (no-op if file missing)."""
        if not self._path.exists():
            self._players = []
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._players = data.get("players", [])
            for p in self._players:
                p.setdefault("god_mode", False)
                p.setdefault("lang", "")
                p.setdefault("last_seen", 0.0)
            logger.info("Loaded %d players from %s",
                        len(self._players), self._path)
        except Exception:
            logger.error("Failed to load player registry", exc_info=True)
            self._players = []

    def _save(self) -> None:
        """Atomic write: tmp file + os.replace."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        payload = json.dumps(
            {"players": self._players}, indent=2, ensure_ascii=False,
        )
        tmp.write_text(payload, encoding="utf-8")
        os.replace(str(tmp), str(self._path))

    # ── Mutations ───────────────────────────────────────────

    def register(self, name: str) -> tuple[str, str]:
        """Register a new player.

        Returns (token, player_id).  The token is shown once to the
        admin; only its hash is stored.
        """
        token = generate_token()
        pid = player_id_from_token(token)
        entry = {
            "player_id": pid,
            "name": name,
            "token_hash": hash_token(token),
            "created_at": time.time(),
            "revoked": False,
            "god_mode": False,
            "lang": "",
            "last_seen": 0.0,
        }
        with self._lock:
            self._players.append(entry)
            self._save()
        logger.info("Registered player %s (%s)", name, pid)
        return token, pid

    def regenerate_token(self, player_id: str) -> str | None:
        """Generate a new token for an existing player.

        Returns the new token, or None if the player was not found.
        The old token is invalidated (hash replaced).
        """
        token = generate_token()
        with self._lock:
            for p in self._players:
                if p["player_id"] == player_id and not p["revoked"]:
                    p["token_hash"] = hash_token(token)
                    self._save()
                    logger.info("Regenerated token for player %s",
                                player_id)
                    return token
        return None

    def revoke(self, player_id: str) -> bool:
        """Revoke a player's access.  Returns True if found."""
        with self._lock:
            for p in self._players:
                if p["player_id"] == player_id:
                    p["revoked"] = True
                    self._save()
                    logger.info("Revoked player %s", player_id)
                    return True
        return False

    def set_god_mode(self, player_id: str, enabled: bool) -> bool:
        """Toggle god mode for a player.  Returns True if found."""
        with self._lock:
            for p in self._players:
                if p["player_id"] == player_id:
                    p["god_mode"] = enabled
                    self._save()
                    logger.info("God mode %s for player %s",
                                "enabled" if enabled else "disabled",
                                player_id)
                    return True
        return False

    def touch(self, player_id: str) -> None:
        """Mark *player_id* as active now.

        The in-memory ``last_seen`` timestamp is always refreshed.
        Disk persistence is throttled to
        :data:`_TOUCH_PERSIST_INTERVAL` per player so that hot
        code paths (every authenticated request) do not thrash
        the registry file.  Unknown player IDs are silently
        ignored — the caller is typically a decorator that has
        already validated the token but does not want to fail
        the request if a race deletes the player.
        """
        now = time.time()
        with self._lock:
            for p in self._players:
                if p["player_id"] != player_id:
                    continue
                prev = float(p.get("last_seen", 0.0))
                p["last_seen"] = now
                if now - prev >= _TOUCH_PERSIST_INTERVAL:
                    try:
                        self._save()
                    except Exception:
                        logger.exception(
                            "Failed to persist last_seen for %s",
                            player_id,
                        )
                return

    def set_lang(self, player_id: str, lang: str) -> bool:
        """Save the player's preferred language.  Returns True if found."""
        with self._lock:
            for p in self._players:
                if p["player_id"] == player_id:
                    p["lang"] = lang
                    self._save()
                    return True
        return False

    # ── Queries ─────────────────────────────────────────────

    def get(self, player_id: str) -> dict | None:
        """Look up a player by ID."""
        for p in self._players:
            if p["player_id"] == player_id:
                return dict(p)
        return None

    def is_valid_token_hash(self, h: str) -> bool:
        """True if the hash belongs to a non-revoked player."""
        for p in self._players:
            if p["token_hash"] == h:
                return not p["revoked"]
        return False

    def player_id_for_hash(self, h: str) -> str:
        """Return the player_id for a token hash, or empty string."""
        for p in self._players:
            if p["token_hash"] == h:
                return p["player_id"]
        return ""

    def list_all(self) -> list[dict]:
        """Return a copy of all player records."""
        return [dict(p) for p in self._players]
