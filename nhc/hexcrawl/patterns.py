"""Feature pattern placement for themed hex clusters.

Patterns are recipes for placing groups of related features
(e.g., a keep with surrounding cave lairs). They run after
basic feature placement, consuming from the dungeon budget.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from nhc.dungeon.generator import Range
from nhc.hexcrawl.coords import HexCoord, distance, neighbors
from nhc.hexcrawl.model import (
    Biome,
    DungeonRef,
    HexCell,
    HexFeatureType,
)


@dataclass
class SatelliteSpec:
    """Specification for satellite features around an anchor."""

    feature: HexFeatureType
    max_distance: int
    count: Range
    biomes: tuple[Biome, ...]
    template_override: str | None = None
    faction_pool: list[str] | None = None


@dataclass
class FeaturePattern:
    """A recipe for placing a cluster of related features."""

    name: str
    anchor_feature: HexFeatureType
    anchor_biomes: tuple[Biome, ...]
    anchor_template: str
    satellite_specs: list[SatelliteSpec]


# ── Caves of Chaos pattern ────────────────────────────────────

_CHAOS_FACTIONS = [
    "goblin", "orc", "kobold", "gnoll", "bugbear", "ogre",
]

CAVES_OF_CHAOS = FeaturePattern(
    name="caves_of_chaos",
    anchor_feature=HexFeatureType.KEEP,
    anchor_biomes=(Biome.GREENLANDS, Biome.HILLS),
    anchor_template="procedural:keep",
    satellite_specs=[
        SatelliteSpec(
            feature=HexFeatureType.CAVE,
            max_distance=2,
            count=Range(3, 5),
            biomes=(
                Biome.GREENLANDS, Biome.HILLS,
                Biome.MOUNTAIN, Biome.FOREST,
            ),
            template_override="procedural:cave",
            faction_pool=_CHAOS_FACTIONS,
        ),
    ],
)

# ── Pattern registry ──────────────────────────────────────────

PATTERNS: dict[str, FeaturePattern] = {
    "caves_of_chaos": CAVES_OF_CHAOS,
}


def place_pattern(
    pattern: FeaturePattern,
    cells: dict[HexCoord, HexCell],
    taken: set[HexCoord],
    rng: random.Random,
) -> bool:
    """Attempt to place a feature pattern on the hex map.

    Returns True if the pattern was successfully placed.
    The anchor and all satellites are stamped onto cells,
    and their coords are added to *taken*.
    """
    # Find a valid anchor position
    anchor_candidates = [
        coord for coord, cell in cells.items()
        if (coord not in taken
            and cell.biome in pattern.anchor_biomes
            and cell.feature == HexFeatureType.NONE)
    ]
    if not anchor_candidates:
        return False

    rng.shuffle(anchor_candidates)

    for anchor_coord in anchor_candidates:
        # Try to place all satellite specs from this anchor
        all_placed = True
        placements: list[tuple[HexCoord, SatelliteSpec, str]] = []

        for spec in pattern.satellite_specs:
            n_satellites = rng.randint(spec.count.min, spec.count.max)
            factions_used: list[str] = []
            faction_pool = list(spec.faction_pool or [])
            rng.shuffle(faction_pool)

            sat_candidates = [
                coord for coord, cell in cells.items()
                if (coord not in taken
                    and coord != anchor_coord
                    and cell.biome in spec.biomes
                    and cell.feature == HexFeatureType.NONE
                    and distance(anchor_coord, coord)
                    <= spec.max_distance
                    and coord not in {p[0] for p in placements})
            ]
            rng.shuffle(sat_candidates)

            placed = 0
            for sc in sat_candidates:
                if placed >= n_satellites:
                    break
                faction = (
                    faction_pool[placed % len(faction_pool)]
                    if faction_pool else None
                )
                placements.append((sc, spec, faction))
                placed += 1

            if placed < spec.count.min:
                all_placed = False
                break

        if not all_placed:
            continue

        # Commit the anchor
        anchor_cell = cells[anchor_coord]
        anchor_cell.feature = pattern.anchor_feature
        anchor_cell.dungeon = DungeonRef(
            template=pattern.anchor_template,
        )
        taken.add(anchor_coord)

        # Commit satellites
        for sat_coord, spec, faction in placements:
            sat_cell = cells[sat_coord]
            sat_cell.feature = spec.feature
            template = spec.template_override or "procedural:cave"
            sat_cell.dungeon = DungeonRef(
                template=template,
                faction=faction,
            )
            taken.add(sat_coord)

        return True

    return False
