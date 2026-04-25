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
    """Thematic weight of a site, sets the map footprint.

    Five-step scale spanning the unified site system after M6a:

    * ``TINY`` -- single-feature sub-hex sites (wayside well /
      signpost / clearing centerpiece).
    * ``SMALL`` -- regular sub-hex sites with a centerpiece on a
      walled field (sacred, animal den, graveyard, campsite,
      orchard, sub-hex farm).
    * ``MEDIUM`` -- smallest macro sites (hamlet, cottage, ruin,
      mage_residence) and oversized sub-hex variants.
    * ``LARGE`` -- mid-tier macros (village, keep, mansion, tower,
      temple).
    * ``HUGE`` -- top-tier settlements (town, city).

    Values map to the canonical footprint via :data:`SITE_TIER_DIMS`;
    individual assemblers may override with their own per-tier
    tables when they have buildings or other size-driven detail
    (see :mod:`nhc.sites.farm`, :mod:`nhc.sites.town`).
    """

    TINY = "tiny"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    HUGE = "huge"


SITE_TIER_DIMS: dict[SiteTier, tuple[int, int]] = {
    SiteTier.TINY: (15, 10),
    SiteTier.SMALL: (30, 22),
    SiteTier.MEDIUM: (48, 44),
    SiteTier.LARGE: (72, 58),
    SiteTier.HUGE: (104, 86),
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
