"""Persistent leaderboard for completed runs.

Stores one entry per completed game (death or victory) at
``{data_dir}/leaderboard.json``.  Thread-safe via a lock and
atomic writes via tmp + os.replace, following the same pattern
as :class:`~nhc.web.registry.PlayerRegistry`.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


VICTORY_BONUS = 5000


def compute_score(
    xp: int, gold: int, depth: int, won: bool,
) -> int:
    """Return the leaderboard score for a completed run.

    The formula is intentionally simple and legible:
    ``xp + gold + (depth - 1) * 100 + victory_bonus``.  Negative
    or zero inputs are clamped so the score never drops below 0.
    """
    xp = max(0, int(xp))
    gold = max(0, int(gold))
    depth = max(1, int(depth))
    bonus = VICTORY_BONUS if won else 0
    return xp + gold + (depth - 1) * 100 + bonus


@dataclass
class LeaderboardEntry:
    """A single completed-run record."""

    player_id: str
    name: str
    score: int
    depth: int
    turn: int
    won: bool
    killed_by: str
    timestamp: float
    rank: int = 0  # populated when read back via top()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> LeaderboardEntry:
        return cls(
            player_id=str(data.get("player_id", "")),
            name=str(data.get("name", "")),
            score=int(data.get("score", 0)),
            depth=int(data.get("depth", 1)),
            turn=int(data.get("turn", 0)),
            won=bool(data.get("won", False)),
            killed_by=str(data.get("killed_by", "")),
            timestamp=float(data.get("timestamp", 0.0)),
        )


class Leaderboard:
    """Manage the completed-run leaderboard on disk."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._entries: list[LeaderboardEntry] = []
        self._lock = threading.Lock()

    # ── Persistence ─────────────────────────────────────────

    def load(self) -> None:
        """Read leaderboard entries from disk (no-op if missing)."""
        if not self._path.exists():
            self._entries = []
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            raw_entries = data.get("entries", [])
            self._entries = [
                LeaderboardEntry.from_dict(e) for e in raw_entries
            ]
            logger.info("Loaded %d leaderboard entries from %s",
                        len(self._entries), self._path)
        except Exception:
            logger.error("Failed to load leaderboard", exc_info=True)
            self._entries = []

    def _save(self) -> None:
        """Atomic write: tmp file + os.replace."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        # Strip the rank field before persisting — it is derived at
        # read time and must not be stored.
        payload = json.dumps(
            {
                "entries": [
                    {k: v for k, v in e.to_dict().items() if k != "rank"}
                    for e in self._entries
                ],
            },
            indent=2,
            ensure_ascii=False,
        )
        tmp.write_text(payload, encoding="utf-8")
        os.replace(str(tmp), str(self._path))

    # ── Mutations ───────────────────────────────────────────

    def submit(self, entry: LeaderboardEntry) -> None:
        """Append an entry and persist."""
        with self._lock:
            # Reset rank on insert — it is assigned by top().
            entry.rank = 0
            self._entries.append(entry)
            self._save()
        logger.info(
            "Leaderboard: submitted %s score=%d depth=%d won=%s",
            entry.name, entry.score, entry.depth, entry.won,
        )

    def remove_player_entries(self, player_id: str) -> int:
        """Remove all entries for *player_id*.  Returns count removed."""
        with self._lock:
            before = len(self._entries)
            self._entries = [
                e for e in self._entries if e.player_id != player_id
            ]
            removed = before - len(self._entries)
            if removed:
                self._save()
        if removed:
            logger.info("Leaderboard: removed %d entries for %s",
                        removed, player_id)
        return removed

    # ── Queries ─────────────────────────────────────────────

    def top(self, limit: int = 10) -> list[LeaderboardEntry]:
        """Return the top *limit* entries, highest score first.

        Ties are broken by earlier submission (lower timestamp
        ranks higher).  The returned entries have their ``rank``
        field populated starting at 1.
        """
        with self._lock:
            ordered = sorted(
                self._entries,
                key=lambda e: (-e.score, e.timestamp),
            )[:max(0, limit)]
        ranked: list[LeaderboardEntry] = []
        for i, e in enumerate(ordered, start=1):
            # Return copies so callers can't mutate internal state.
            copy = LeaderboardEntry(
                player_id=e.player_id, name=e.name,
                score=e.score, depth=e.depth, turn=e.turn,
                won=e.won, killed_by=e.killed_by,
                timestamp=e.timestamp, rank=i,
            )
            ranked.append(copy)
        return ranked

    def all_entries(self) -> list[LeaderboardEntry]:
        """Return every stored entry (unranked, for tests/admin)."""
        with self._lock:
            return list(self._entries)
