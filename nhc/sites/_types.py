"""Shared types for sub-hex site assemblers and dispatchers.

These types used to live in ``nhc.hexcrawl.sub_hex_sites`` alongside
the family generators. After M4f every family generator moved to its
own module under ``nhc/sites/``; M5 folds the remaining types here
so the ``nhc/hexcrawl/`` package no longer carries sites concepts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from nhc.dungeon.model import Level


class SiteTier(Enum):
    """Thematic weight of a sub-hex site, sets the map footprint."""

    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


SITE_TIER_DIMS: dict[SiteTier, tuple[int, int]] = {
    SiteTier.SMALL: (15, 10),
    SiteTier.MEDIUM: (30, 20),
    SiteTier.LARGE: (50, 30),
}


@dataclass
class SubHexPopulation:
    """Entity placement spec for a sub-hex family site.

    Each list holds ``(registry_id, (x, y))`` tuples. The
    populator walks the lists and creates the matching ECS
    entities via :class:`EntityRegistry`. ``features`` is for
    non-entity tile tags the generator wants to stamp onto the
    level (currently unused — kept for parity with the plan).
    """

    creatures: list[tuple[str, tuple[int, int]]] = field(
        default_factory=list,
    )
    npcs: list[tuple[str, tuple[int, int]]] = field(
        default_factory=list,
    )
    items: list[tuple[str, tuple[int, int]]] = field(
        default_factory=list,
    )
    features: list[tuple[str, tuple[int, int]]] = field(
        default_factory=list,
    )


@dataclass
class SubHexSite:
    """Bundle produced by a family generator.

    - ``level`` — the :class:`~nhc.dungeon.model.Level` the player
      walks around on.
    - ``entry_tile`` — the "front door" coord the player lands on
      when entering from the flower.
    - ``feature_tile`` — the centrepiece (well, shrine, signpost,
      den mouth, etc.) the player interacts with. ``None`` for
      families with no single central tile.
    - ``faction`` — optional creature faction for the populator.
    - ``population`` — :class:`SubHexPopulation` listing the
      creatures, NPCs, items, and feature tags the populator will
      spawn on entry.
    """

    level: Level
    entry_tile: tuple[int, int]
    feature_tile: tuple[int, int] | None = None
    faction: str | None = None
    population: "SubHexPopulation" = field(
        default_factory=lambda: SubHexPopulation(),
    )
