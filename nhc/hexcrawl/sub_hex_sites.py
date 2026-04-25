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
# Shared helpers
# ---------------------------------------------------------------------------


def _make_enclosed_level(
    *,
    width: int,
    height: int,
    level_id: str,
    name: str,
    theme: str,
) -> Level:
    """Build a Level with a walkable interior and a wall perimeter.

    Sub-hex sites are deliberately small and unfussy: a filled
    rectangle with a 1-tile wall border so the player can't walk
    off the map by accident (leave-site uses the overland exit
    mechanic instead — see `nhc_leave_site_plan.md`).
    """
    level = Level.create_empty(
        id=level_id, name=name, depth=1,
        width=width, height=height,
    )
    level.metadata.theme = theme
    level.metadata.prerevealed = True
    for y in range(height):
        for x in range(width):
            tile = level.tiles[y][x]
            if x == 0 or y == 0 or x == width - 1 or y == height - 1:
                tile.terrain = Terrain.WALL
            else:
                tile.terrain = Terrain.FLOOR
    return level


def _south_gate_entry(width: int, height: int) -> tuple[int, int]:
    """Put the player on the walkable tile just inside the south edge.

    Sub-hex sites are reached from the overland, so the canonical
    front door is a gap in the south wall. Uniform across families
    so player muscle memory carries over.
    """
    return (width // 2, height - 2)


def _central_feature_tile(
    width: int, height: int, rng: random.Random,
) -> tuple[int, int]:
    """Pick a walkable tile near the centre for the centrepiece.

    Adds a small jitter so repeated visits to similar features in
    the same flower don't all stamp the exact centre of the map.
    """
    cx, cy = width // 2, height // 2
    jitter_x = rng.randint(-1, 1)
    jitter_y = rng.randint(-1, 1)
    return (cx + jitter_x, cy + jitter_y)


def _tag_feature(
    level: Level, coord: tuple[int, int], feature: str,
) -> None:
    """Stamp ``feature`` onto the tile at ``coord`` (and make it walkable)."""
    x, y = coord
    tile = level.tile_at(x, y)
    if tile is None:
        return
    tile.terrain = Terrain.FLOOR
    tile.feature = feature


# ---------------------------------------------------------------------------
# Family: wayside (well, signpost) — retired
# ---------------------------------------------------------------------------
#
# Waysides now route through :func:`nhc.sites.wayside.assemble_wayside`
# and :meth:`Game._enter_sub_hex_wayside`. The family generator was
# deleted in the sites-unification milestone 4a; keep this header
# as a breadcrumb so grep for "wayside" still lands here.


# ---------------------------------------------------------------------------
# Family: sacred site — retired
# ---------------------------------------------------------------------------
#
# Sacred sites now route through
# :func:`nhc.sites.sacred.assemble_sacred` and
# :meth:`Game._enter_sub_hex_sacred` (milestone 4d).


# ---------------------------------------------------------------------------
# Family: inhabited settlement (farm minor, campsite, orchard)
# ---------------------------------------------------------------------------


_INHABITED_TAGS: dict[MinorFeatureType, str] = {
    MinorFeatureType.CAMPSITE: "campfire",
    MinorFeatureType.ORCHARD: "tree",
}

_INHABITED_NPCS: dict[MinorFeatureType, str] = {
    MinorFeatureType.CAMPSITE: "campsite_traveller",
    MinorFeatureType.ORCHARD: "orchardist",
}


def _adjacent_walkable(
    width: int, height: int, center: tuple[int, int],
) -> tuple[int, int]:
    """Pick the tile immediately south of ``center`` (inside the
    walkable interior) for the NPC. Falls back to ``center`` when
    that lands on the wall border, which only happens on degenerate
    centre picks inside tiny tiers."""
    cx, cy = center
    ny = cy + 1
    if 0 < ny < height - 1 and 0 < cx < width - 1:
        return (cx, ny)
    return center


def generate_inhabited_settlement_site(
    *,
    feature: "HexFeatureType | MinorFeatureType",
    biome: Biome,
    seed: int,
    tier: SiteTier,
) -> SubHexSite:
    """A minor campsite / orchard, medium footprint.

    ORCHARD scatters several tree tiles in a rough grid around the
    orchardist. CAMPSITE stays an open clearing with a campfire
    tile — sitting down under the sky is the whole point. FARM
    used to share this path but now routes through the unified
    farm assembler (see :func:`nhc.sites.farm.assemble_farm` and
    :meth:`Game._enter_sub_hex_farm`); the generator rejects FARM
    so stale callers are caught loudly rather than silently
    producing a bare rectangle.
    """
    if feature is MinorFeatureType.FARM:
        raise ValueError(
            "FARM no longer routes through "
            "generate_inhabited_settlement_site — use "
            "nhc.sites.farm.assemble_farm(tier=SiteTier.SMALL).",
        )
    width, height = SITE_TIER_DIMS[tier]
    rng = random.Random(seed)
    level = _make_enclosed_level(
        width=width, height=height,
        level_id=f"sub_inhabited_{seed}",
        name="settlement", theme="settlement",
    )
    population = SubHexPopulation()

    if feature is MinorFeatureType.ORCHARD:
        center = _central_feature_tile(width, height, rng)
        _tag_feature(level, center, "tree")
        _scatter_orchard_trees(level, center, rng)
        population.npcs.append(
            ("orchardist", _adjacent_walkable(width, height, center)),
        )
        feature_tile = center
    else:
        # CAMPSITE and any HexFeatureType fallback (unused today
        # — no macro feature routes here — but keeps the function
        # total over the union type).
        center = _central_feature_tile(width, height, rng)
        tag = (
            _INHABITED_TAGS.get(feature, "campfire")
            if isinstance(feature, MinorFeatureType)
            else "campfire"
        )
        _tag_feature(level, center, tag)
        if isinstance(feature, MinorFeatureType):
            npc_id = _INHABITED_NPCS.get(feature)
            if npc_id is not None:
                population.npcs.append(
                    (npc_id, _adjacent_walkable(width, height, center)),
                )
        feature_tile = center

    return SubHexSite(
        level=level,
        entry_tile=_south_gate_entry(width, height),
        feature_tile=feature_tile,
        population=population,
    )


def _scatter_orchard_trees(
    level: Level, center: tuple[int, int], rng: random.Random,
) -> None:
    """Stamp a rough 3×3 grid of trees around ``center``.

    The grid stride is ~3 tiles so the rows read as planted,
    not random forest. The centre tile is already tagged
    (``tree``) by the caller; this fills the other eight grid
    slots, skipping any that fall on the perimeter or overlap
    a non-FLOOR tile the generator may add later.
    """
    cx, cy = center
    stride = 3
    jitter = lambda: rng.randint(-1, 1)                    # noqa: E731
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            tx = cx + dx * stride + jitter()
            ty = cy + dy * stride + jitter()
            tile = level.tile_at(tx, ty)
            if tile is None or tile.terrain is not Terrain.FLOOR:
                continue
            if tile.feature:
                continue
            tile.feature = "tree"


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
