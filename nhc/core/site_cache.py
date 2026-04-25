"""Bounded LRU cache for site surfaces with sparse mutation persistence.

The flower view's site entry dispatcher (``nhc/core/hex_session.py``)
generates a per-flower-feature site Level — farm, shrine, well, town,
keep, etc. — on first visit and hands it to :class:`~nhc.core.game.Game`'s
cache. With many macro hexes (and 19 sub-hexes per flower) this would
grow unbounded, so we keep only the 32 most recently used site levels
in memory.

On eviction we serialise the *player-induced* changes (loot removed,
creatures killed, door states, terrain mutations) to a JSON file under
``data_dir/players/<pid>/sub_hex_cache/<key>.json``. The on-disk
subdirectory name is ``sub_hex_cache`` for back-compat with pre-M6d
saves; the manager itself is the unified site cache. Re-entering the
same site later regenerates the layout from the deterministic seed,
applies the persisted mutations, and deletes the record file. That
keeps the on-disk footprint proportional to "places the player
actually touched" rather than "places they could have touched."

Today this manager only handles sub-hex site keys
(``("sub", macro_q, macro_r, sub_q, sub_r, depth)``). M6d-2 generalises
the key + path strategy so macro site keys
(``("site", q, r, depth)``) and any future site-shaped key can flow
through the same LRU + mutation pipeline.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path
from typing import Any

# Two key shapes after M6d-2:
#   ("sub",  macro_q, macro_r, sub_q, sub_r, depth)  -- sub-hex sites
#   ("site", q, r, depth)                            -- macro sites
# The on-disk path strategy (``_path_for``) dispatches on key[0].
SiteKey = tuple

DEFAULT_CAPACITY: int = 32


class SiteCacheManager:
    """LRU + disk-persisted mutation store for site surfaces.

    Renamed from ``SubHexCacheManager`` in M6d-1; today it still
    only serves sub-hex sites. M6d-2 broadens the key/path
    strategy to also cover macro sites; M6d-3 migrates the macro
    entry methods onto this manager.
    """

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
        self._entries: "OrderedDict[SiteKey, dict[str, Any]]" = (
            OrderedDict()
        )

    # -- path helpers -----------------------------------------------

    def _cache_dir(self) -> Path:
        return (
            self.storage_dir / "players" / self.player_id
            / "sub_hex_cache"
        )

    def _path_for(self, key: SiteKey) -> Path:
        """On-disk filename for *key*.

        Sub-hex keys keep their pre-M6d filename
        (``{mq}_{mr}_{sq}_{sr}.json``) so old mutation records
        on disk still load. Macro site keys land under a
        ``site_{q}_{r}.json`` name -- the prefix disambiguates
        the two key shapes living in the same directory.
        """
        if key[0] == "sub":
            _, mq, mr, sq, sr, _depth = key
            return self._cache_dir() / f"{mq}_{mr}_{sq}_{sr}.json"
        if key[0] == "site":
            _, q, r, _depth = key
            return self._cache_dir() / f"site_{q}_{r}.json"
        raise ValueError(f"unknown site cache key shape: {key!r}")

    # -- core cache API ---------------------------------------------

    def has(self, key: SiteKey) -> bool:
        return key in self._entries

    def get(self, key: SiteKey) -> Any | None:
        """Return the cached level (promoting to MRU) or ``None``."""
        entry = self._entries.get(key)
        if entry is None:
            return None
        self._entries.move_to_end(key)
        return entry["level"]

    def store(
        self,
        key: SiteKey,
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
        self, key: SiteKey, mutations: dict[str, Any],
    ) -> None:
        """Overwrite the mutation record attached to a cached level."""
        entry = self._entries.get(key)
        if entry is None:
            return
        entry["mutations"] = dict(mutations)
        self._entries.move_to_end(key)

    # -- mutation persistence --------------------------------------

    def _persist_mutations(
        self, key: SiteKey, mutations: dict[str, Any],
    ) -> None:
        """Write the sparse mutation record to disk on eviction.

        No-op when the record is empty — there is nothing worth
        replaying on re-entry.
        """
        if not mutations:
            return
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {"mutations": mutations}
        if key[0] == "sub":
            _, mq, mr, sq, sr, _depth = key
            payload["macro"] = [mq, mr]
            payload["sub"] = [sq, sr]
        elif key[0] == "site":
            _, q, r, _depth = key
            payload["macro"] = [q, r]
        path.write_text(json.dumps(payload))

    def gc_old_records(self, *, max_age_days: int = 90) -> int:
        """Delete persisted mutation records older than ``max_age_days``.

        Returns the number of files unlinked. No-op when the cache
        directory doesn't exist yet. Called from the Game autosave
        path so long-abandoned records don't linger forever.
        """
        import time

        cache_dir = self._cache_dir()
        if not cache_dir.exists():
            return 0
        cutoff = time.time() - max_age_days * 24 * 60 * 60
        unlinked = 0
        for path in cache_dir.glob("*.json"):
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime >= cutoff:
                continue
            try:
                path.unlink()
                unlinked += 1
            except OSError:
                pass
        return unlinked

    def load_mutations(self, key: SiteKey) -> dict[str, Any]:
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
