"""Bounded LRU cache for sub-hex sites with sparse mutation persistence.

The flower view's sub-hex entry dispatcher (``nhc/core/hex_session.py``)
generates a small per-sub-hex map — farm, shrine, well, signpost — on
first visit and hands the Level back to :class:`~nhc.core.game.Game`'s
floor cache. With 19 sub-hexes per flower and many macro hexes this
would grow unbounded, so we keep only the 32 most recently used
sub-hex levels in memory.

On eviction we serialise the *player-induced* changes (loot removed,
creatures killed, door states, terrain mutations) to a JSON file under
``data_dir/players/<pid>/sub_hex_cache/<macro_q>_<macro_r>_<sub_q>_<sub_r>.json``.
Re-entering the same sub-hex later regenerates the layout from the
deterministic seed, applies the persisted mutations, and deletes the
record file. That keeps the on-disk footprint proportional to "places
the player actually touched" rather than "places they could have
touched."
"""

from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path
from typing import Any

SubHexKey = tuple  # ("sub", macro_q, macro_r, sub_q, sub_r, depth)

DEFAULT_CAPACITY: int = 32


class SubHexCacheManager:
    """LRU + disk-persisted mutation store for sub-hex site floors."""

    def __init__(
        self,
        *,
        capacity: int = DEFAULT_CAPACITY,
        storage_dir: Path,
        player_id: str,
    ) -> None:
        self.capacity = capacity
        self.storage_dir = Path(storage_dir)
        self.player_id = player_id
        # OrderedDict preserves insertion order; we promote on access
        # with ``move_to_end`` and evict ``popitem(last=False)`` to
        # drop the oldest entry.
        self._entries: "OrderedDict[SubHexKey, dict[str, Any]]" = (
            OrderedDict()
        )

    # -- path helpers -----------------------------------------------

    def _cache_dir(self) -> Path:
        return (
            self.storage_dir / "players" / self.player_id
            / "sub_hex_cache"
        )

    def _path_for(self, key: SubHexKey) -> Path:
        _, mq, mr, sq, sr, _depth = key
        return self._cache_dir() / f"{mq}_{mr}_{sq}_{sr}.json"

    # -- core cache API ---------------------------------------------

    def has(self, key: SubHexKey) -> bool:
        return key in self._entries

    def get(self, key: SubHexKey) -> Any | None:
        """Return the cached level (promoting to MRU) or ``None``."""
        entry = self._entries.get(key)
        if entry is None:
            return None
        self._entries.move_to_end(key)
        return entry["level"]

    def store(
        self,
        key: SubHexKey,
        level: Any,
        *,
        mutations: dict[str, Any] | None = None,
    ) -> None:
        """Insert or update an entry, evicting the oldest if full."""
        if key in self._entries:
            self._entries[key] = {
                "level": level,
                "mutations": dict(mutations or {}),
            }
            self._entries.move_to_end(key)
            return
        self._entries[key] = {
            "level": level,
            "mutations": dict(mutations or {}),
        }
        self._entries.move_to_end(key)
        while len(self._entries) > self.capacity:
            oldest_key, oldest_entry = self._entries.popitem(last=False)
            self._persist_mutations(oldest_key, oldest_entry["mutations"])

    def update_mutations(
        self, key: SubHexKey, mutations: dict[str, Any],
    ) -> None:
        """Overwrite the mutation record attached to a cached level."""
        entry = self._entries.get(key)
        if entry is None:
            return
        entry["mutations"] = dict(mutations)
        self._entries.move_to_end(key)

    # -- mutation persistence --------------------------------------

    def _persist_mutations(
        self, key: SubHexKey, mutations: dict[str, Any],
    ) -> None:
        """Write the sparse mutation record to disk on eviction.

        No-op when the record is empty — there is nothing worth
        replaying on re-entry.
        """
        if not mutations:
            return
        _, mq, mr, sq, sr, _depth = key
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "macro": [mq, mr],
            "sub": [sq, sr],
            "mutations": mutations,
        }
        path.write_text(json.dumps(payload))

    def load_mutations(self, key: SubHexKey) -> dict[str, Any]:
        """Load and delete the persisted mutation record for *key*.

        Returns an empty dict when no record exists. The file is
        removed after a successful read so the next eviction can
        re-serialise cleanly without merging old state.
        """
        path = self._path_for(key)
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}
        finally:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        return dict(payload.get("mutations", {}))
