"""Family-based generators for sub-hex minor-feature sites.

The flower view's sub-hex entry dispatcher (see M4 of the sub-hex
entry plan) routes most minor features through these family
generators; the handful of macro features with hand-tuned bespoke
generators (town, keep, tower, mansion, farm, etc.) keep their
existing paths.

Families
--------
- Inhabited settlement — farm minor, campsite, orchard. One
  farmhouse and a fenced field.
- Sacred site — shrine, standing_stone, cairn, crystals, stones,
  wonder, portal. Small plaza with a centrepiece.
- Natural curiosity — mushroom_ring, herb_patch, hollow_log,
  bone_pile. A tiny clearing with one gather-tile.
- Animal den — animal_den, lair, nest, burrow. A cave-mouth lair
  the player steps into.
- Undead — graveyard. A stone-walled yard with a tomb entrance.
- Wayside — well, signpost. A tiny clearing with a single
  interactable tile.

Each generator returns a :class:`SubHexSite` bundle with the Level,
the entry tile (the "front door" the player lands on) and the
centerpiece feature tile coord.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum

from nhc.dungeon.model import Level, Terrain
from nhc.hexcrawl.model import Biome, HexFeatureType, MinorFeatureType


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


# ---------------------------------------------------------------------------
# Family generators -- all retired
# ---------------------------------------------------------------------------
#
# Every family generator that used to live here now routes through
# a per-family assembler under ``nhc/sites/`` and a corresponding
# ``Game._enter_sub_hex_<family>`` dispatcher:
#
# - wayside  -> :func:`nhc.sites.wayside.assemble_wayside`     (M4a)
# - clearing -> :func:`nhc.sites.clearing.assemble_clearing`   (M4b)
# - den      -> :func:`nhc.sites.den.assemble_den`             (M4c)
# - sacred   -> :func:`nhc.sites.sacred.assemble_sacred`       (M4d)
# - graveyard-> :func:`nhc.sites.graveyard.assemble_graveyard` (M4e)
# - campsite -> :func:`nhc.sites.campsite.assemble_campsite`   (M4f)
# - orchard  -> :func:`nhc.sites.orchard.assemble_orchard`     (M4f)
#
# FARM (minor) routes through :func:`nhc.sites.farm.assemble_farm`
# at ``tier=SMALL``. After milestone 4f this module only carries the
# shared types (``SiteTier``, ``SubHexPopulation``, ``SubHexSite``,
# ``SITE_TIER_DIMS``) used by the assemblers and dispatchers; M5
# folds those into ``nhc/sites/_types.py`` once the dispatcher
# unification lands.


# ---------------------------------------------------------------------------
# Family: animal den (lair, nest, burrow, animal_den) — retired
# ---------------------------------------------------------------------------
#
# Dens now route through :func:`nhc.sites.den.assemble_den` and
# :meth:`Game._enter_sub_hex_den` (milestone 4c). The biome →
# faction mapping moved alongside the assembler.


# ---------------------------------------------------------------------------
# Family: natural curiosity (mushroom_ring, herb_patch, hollow_log,
# bone_pile) — retired
# ---------------------------------------------------------------------------
#
# Natural curiosities now route through
# :func:`nhc.sites.clearing.assemble_clearing` and
# :meth:`Game._enter_sub_hex_clearing` (milestone 4b).


# ---------------------------------------------------------------------------
# Family: undead (graveyard) — retired
# ---------------------------------------------------------------------------
#
# Graveyards now route through
# :func:`nhc.sites.graveyard.assemble_graveyard` and
# :meth:`Game._enter_sub_hex_graveyard` (milestone 4e). The
# tier-scaled undead pool moved alongside the assembler as
# ``UNDEAD_POOL_BY_TIER`` / ``UNDEAD_COUNT_BY_TIER`` and
# ``pick_undead_population``.
