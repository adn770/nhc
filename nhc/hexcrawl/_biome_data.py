"""Shared biome constants for the hexcrawl generator pipeline.

Centralises biome feature sets, cost tables, and role groupings
that were previously scattered across _rivers.py, _paths.py,
_features.py, and _features_scored.py.
"""

from __future__ import annotations

from nhc.hexcrawl.model import Biome, HexFeatureType


# ── Feature sets ──────────────────────────────────────────────

SETTLEMENT_FEATURES: frozenset[HexFeatureType] = frozenset({
    HexFeatureType.CITY,
    HexFeatureType.VILLAGE,
})

TOWER_FEATURES: frozenset[HexFeatureType] = frozenset({
    HexFeatureType.TOWER,
    HexFeatureType.KEEP,
})


# ── Biome role sets (rivers) ─────────────────────────────────

TERMINAL_BIOMES: frozenset[Biome] = frozenset({
    Biome.DRYLANDS, Biome.SANDLANDS,
})

LAKE_BIOMES: frozenset[Biome] = frozenset({
    Biome.GREENLANDS, Biome.MARSH,
})

SOURCE_BIOMES: frozenset[Biome] = frozenset({
    Biome.MOUNTAIN, Biome.HILLS,
})

LAKE_ELEVATION_MAX: float = 0.15


# ── Road costs ────────────────────────────────────────────────

ROAD_COSTS: dict[Biome, int] = {
    Biome.GREENLANDS: 1,
    Biome.HILLS: 2,
    Biome.DRYLANDS: 3,
    Biome.MARSH: 3,
    Biome.SWAMP: 4,
    Biome.ICELANDS: 5,
    Biome.FOREST: 6,
    Biome.MOUNTAIN: 8,
    Biome.SANDLANDS: 15,
    Biome.DEADLANDS: 15,
    Biome.WATER: 99,
}


# ── Settlement candidate biomes ───────────────────────────────

CANDIDATE_BIOMES: frozenset[Biome] = frozenset({
    Biome.GREENLANDS,
    Biome.HILLS,
    Biome.FOREST,
    Biome.DRYLANDS,
    Biome.SANDLANDS,
    Biome.MARSH,
    Biome.SWAMP,
})

BIOME_SETTLEMENT_BONUS: dict[Biome, float] = {
    Biome.GREENLANDS: 2.0,
    Biome.HILLS: 1.5,
    Biome.FOREST: 0.5,
    Biome.DRYLANDS: 0.5,
    Biome.SANDLANDS: -1.0,
    Biome.MARSH: -1.0,
    Biome.SWAMP: -2.0,
}
