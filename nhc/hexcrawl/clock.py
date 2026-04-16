"""Day-clock helpers: biome-dependent step costs.

The raw clock lives on :class:`HexWorld` (see :meth:`HexWorld.
advance_clock`). This module contributes the lookup that maps a
biome (optionally a modifier) to a number of time-of-day segments,
and a convenience on :class:`HexWorld` that performs a cell-based
step in one call.
"""

from __future__ import annotations

from nhc.hexcrawl.model import Biome
from nhc.hexcrawl.pack import DEFAULT_BIOME_COSTS


def cost_for(
    biome: Biome,
    costs: dict[Biome, int] | None = None,
) -> int:
    """Segments consumed by one step into a hex of ``biome``.

    ``costs`` is an optional override table (typically
    ``PackMeta.biome_costs`` or ``HexWorld.biome_costs``). Any biome
    missing from the override falls through to :data:`DEFAULT_BIOME_COSTS`.
    """
    if costs is not None and biome in costs:
        return costs[biome]
    return DEFAULT_BIOME_COSTS[biome]
