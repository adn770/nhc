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
# Family: wayside (well, signpost) — small tier
# ---------------------------------------------------------------------------


def generate_wayside_site(
    *,
    feature: "HexFeatureType | MinorFeatureType",
    biome: Biome,
    seed: int,
    tier: SiteTier,
) -> SubHexSite:
    """A tiny clearing with one interactable tile.

    Handles WELL and SIGNPOST. The interactable tile is tagged on
    the Level and also returned as ``feature_tile`` so the
    dispatcher can wire the right action (rumour roll for a well,
    rumour dispense for a signpost). SIGNPOST sites drop a
    ``rumor_sign`` feature entity on the centrepiece so BumpAction
    can dispatch :class:`SignReadAction`.
    """
    width, height = SITE_TIER_DIMS[tier]
    rng = random.Random(seed)
    level = _make_enclosed_level(
        width=width, height=height,
        level_id=f"sub_wayside_{seed}",
        name="wayside", theme="wayside",
    )
    center = _central_feature_tile(width, height, rng)
    population = SubHexPopulation()
    if isinstance(feature, MinorFeatureType) and feature is MinorFeatureType.WELL:
        tag = "well"
        population.features.append(("well_drink", center))
    elif isinstance(feature, MinorFeatureType) and feature is MinorFeatureType.SIGNPOST:
        tag = "signpost"
        population.features.append(("rumor_sign", center))
    else:
        tag = "landmark"
    _tag_feature(level, center, tag)
    return SubHexSite(
        level=level,
        entry_tile=_south_gate_entry(width, height),
        feature_tile=center,
        population=population,
    )


# ---------------------------------------------------------------------------
# Family: sacred site — medium tier
# ---------------------------------------------------------------------------


_SACRED_TAGS: dict[MinorFeatureType, str] = {
    MinorFeatureType.SHRINE: "shrine",
    MinorFeatureType.STANDING_STONE: "monolith",
    MinorFeatureType.CAIRN: "cairn",
}

_SACRED_HEX_TAGS: dict[HexFeatureType, str] = {
    HexFeatureType.CRYSTALS: "crystals",
    HexFeatureType.STONES: "monolith",
    HexFeatureType.WONDER: "wonder",
    HexFeatureType.PORTAL: "portal",
}


def generate_sacred_site(
    *,
    feature: "HexFeatureType | MinorFeatureType",
    biome: Biome,
    seed: int,
    tier: SiteTier,
) -> SubHexSite:
    """A plaza with an altar / monolith centrepiece."""
    width, height = SITE_TIER_DIMS[tier]
    rng = random.Random(seed)
    level = _make_enclosed_level(
        width=width, height=height,
        level_id=f"sub_sacred_{seed}",
        name="sacred", theme="sacred",
    )
    center = _central_feature_tile(width, height, rng)
    tag = _SACRED_HEX_TAGS.get(feature) if isinstance(feature, HexFeatureType) else None
    if tag is None:
        tag = _SACRED_TAGS.get(feature, "shrine")
    _tag_feature(level, center, tag)
    return SubHexSite(
        level=level,
        entry_tile=_south_gate_entry(width, height),
        feature_tile=center,
    )


# ---------------------------------------------------------------------------
# Family: inhabited settlement (farm minor, campsite, orchard)
# ---------------------------------------------------------------------------


_INHABITED_TAGS: dict[MinorFeatureType, str] = {
    MinorFeatureType.FARM: "farmhouse_door",
    MinorFeatureType.CAMPSITE: "campfire",
    MinorFeatureType.ORCHARD: "tree",
}


def generate_inhabited_settlement_site(
    *,
    feature: "HexFeatureType | MinorFeatureType",
    biome: Biome,
    seed: int,
    tier: SiteTier,
) -> SubHexSite:
    """A minor farmhouse / campsite / orchard, medium footprint.

    Single interactable centrepiece in v1; the rumour-dispensing
    NPC gets plugged in by the populator step in M4.
    """
    width, height = SITE_TIER_DIMS[tier]
    rng = random.Random(seed)
    level = _make_enclosed_level(
        width=width, height=height,
        level_id=f"sub_inhabited_{seed}",
        name="settlement", theme="settlement",
    )
    center = _central_feature_tile(width, height, rng)
    tag = (
        _INHABITED_TAGS.get(feature, "farmhouse_door")
        if isinstance(feature, MinorFeatureType)
        else "farmhouse_door"
    )
    _tag_feature(level, center, tag)
    return SubHexSite(
        level=level,
        entry_tile=_south_gate_entry(width, height),
        feature_tile=center,
    )


# ---------------------------------------------------------------------------
# Family: animal den (lair, nest, burrow, animal_den)
# ---------------------------------------------------------------------------


def generate_animal_den_site(
    *,
    feature: "HexFeatureType | MinorFeatureType",
    biome: Biome,
    seed: int,
    tier: SiteTier,
) -> SubHexSite:
    """A cave-mouth lair. Creature pool scales with biome + feature."""
    width, height = SITE_TIER_DIMS[tier]
    rng = random.Random(seed)
    level = _make_enclosed_level(
        width=width, height=height,
        level_id=f"sub_den_{seed}",
        name="animal_den", theme="den",
    )
    center = _central_feature_tile(width, height, rng)
    _tag_feature(level, center, "den_mouth")
    return SubHexSite(
        level=level,
        entry_tile=_south_gate_entry(width, height),
        feature_tile=center,
        faction=_biome_creature_faction(biome),
    )


def _biome_creature_faction(biome: Biome) -> str | None:
    """Default creature faction for an animal-den level."""
    if biome in (Biome.DEADLANDS, Biome.SWAMP, Biome.MARSH):
        return "undead"
    if biome is Biome.FOREST:
        return "forest_beasts"
    if biome is Biome.MOUNTAIN:
        return "mountain_beasts"
    return "beasts"


# ---------------------------------------------------------------------------
# Family: natural curiosity (mushroom_ring, herb_patch, hollow_log,
# bone_pile) — small tier
# ---------------------------------------------------------------------------


_CURIOSITY_TAGS: dict[MinorFeatureType, str] = {
    MinorFeatureType.MUSHROOM_RING: "mushrooms",
    MinorFeatureType.HERB_PATCH: "herbs",
    MinorFeatureType.HOLLOW_LOG: "hollow_log",
    MinorFeatureType.BONE_PILE: "bones",
}


def generate_natural_curiosity_site(
    *,
    feature: "HexFeatureType | MinorFeatureType",
    biome: Biome,
    seed: int,
    tier: SiteTier,
) -> SubHexSite:
    width, height = SITE_TIER_DIMS[tier]
    rng = random.Random(seed)
    level = _make_enclosed_level(
        width=width, height=height,
        level_id=f"sub_curiosity_{seed}",
        name="curiosity", theme="wilderness",
    )
    center = _central_feature_tile(width, height, rng)
    tag = (
        _CURIOSITY_TAGS.get(feature, "mushrooms")
        if isinstance(feature, MinorFeatureType)
        else "mushrooms"
    )
    _tag_feature(level, center, tag)
    return SubHexSite(
        level=level,
        entry_tile=_south_gate_entry(width, height),
        feature_tile=center,
    )


# ---------------------------------------------------------------------------
# Family: undead (graveyard)
# ---------------------------------------------------------------------------


def generate_undead_site(
    *,
    feature: "HexFeatureType | MinorFeatureType",
    biome: Biome,
    seed: int,
    tier: SiteTier,
) -> SubHexSite:
    """Stone-walled graveyard with a tomb-entrance centrepiece."""
    width, height = SITE_TIER_DIMS[tier]
    rng = random.Random(seed)
    level = _make_enclosed_level(
        width=width, height=height,
        level_id=f"sub_undead_{seed}",
        name="graveyard", theme="crypt",
    )
    center = _central_feature_tile(width, height, rng)
    _tag_feature(level, center, "tomb_entrance")
    return SubHexSite(
        level=level,
        entry_tile=_south_gate_entry(width, height),
        feature_tile=center,
        faction="undead",
    )
