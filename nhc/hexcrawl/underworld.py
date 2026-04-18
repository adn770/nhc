"""Underworld region system for multi-level cave clusters.

Cave clusters of varying sizes produce underground regions
with depth proportional to their surface footprint. Larger
clusters have more floors and deeper biome themes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from nhc.hexcrawl.coords import HexCoord


@dataclass
class UnderworldRegion:
    """A contiguous underground region spanning multiple hexes.

    All member caves share floors at depth >= 2. The canonical
    coord identifies the cluster and keys the floor cache.
    """

    canonical_coord: HexCoord
    member_coords: list[HexCoord]
    max_depth: int
    biome: str = "cave"
    name_key: str | None = None


# ── Depth scaling ─────────────────────────────────────────────

def max_depth_for_cluster(size: int) -> int:
    """Determine max dungeon depth from cluster size.

    | Cluster Size | Max Depth | Classification |
    |-------------|-----------|----------------|
    | 1           | 2         | Cave           |
    | 2-3         | 3         | Cave Complex   |
    | 4-6         | 4         | Underworld     |
    | 7+          | 5         | Moria-scale    |
    """
    if size >= 7:
        return 5
    if size >= 4:
        return 4
    if size >= 2:
        return 3
    return 2


# ── Biome progression ────────────────────────────────────────

def theme_for_underworld_depth(depth: int) -> str:
    """Return the theme for a given underworld floor depth.

    | Floor | Theme           |
    |-------|-----------------|
    | 1-2   | cave            |
    | 3     | fungal_cavern   |
    | 4     | lava_chamber    |
    | 5     | underground_lake|
    """
    if depth <= 2:
        return "cave"
    if depth == 3:
        return "fungal_cavern"
    if depth == 4:
        return "lava_chamber"
    return "underground_lake"


# ── Floor sizing ──────────────────────────────────────────────

def floor_dimensions(
    n_members: int, depth: int,
) -> tuple[int, int]:
    """Compute floor map dimensions from cluster size and depth.

    Width:  50 + n*15 + (depth-1)*10
    Height: 30 + n*10 + (depth-1)*5
    """
    w = 50 + n_members * 15 + (depth - 1) * 10
    h = 30 + n_members * 10 + (depth - 1) * 5
    return w, h


def assign_sector_map(
    level: "Level",
    stairs_by_member: dict[HexCoord, tuple[int, int]],
) -> dict[tuple[int, int], HexCoord]:
    """Partition a shared underworld floor into member sectors.

    Every FLOOR tile is assigned to the member whose stairs_up
    position has the smallest Manhattan distance. Ties break by
    the iteration order of *stairs_by_member*, which is keyed on
    ``HexCoord`` and therefore stable per call.

    Used by the game loop to tell which surface hex the player is
    currently "under" on a shared underworld floor.
    """
    # Lazy import keeps the module importable by tests that build
    # synthetic Level objects without pulling the whole dungeon
    # package at import time.
    from nhc.dungeon.model import Terrain

    if not stairs_by_member:
        return {}

    items = list(stairs_by_member.items())
    sector_map: dict[tuple[int, int], HexCoord] = {}
    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            if tile.terrain is not Terrain.FLOOR:
                continue
            best_member = items[0][0]
            best_dist = abs(x - items[0][1][0]) + abs(y - items[0][1][1])
            for member, (sx, sy) in items[1:]:
                d = abs(x - sx) + abs(y - sy)
                if d < best_dist:
                    best_dist = d
                    best_member = member
            sector_map[(x, y)] = best_member
    return sector_map


def build_regions(
    clusters: dict[HexCoord, list[HexCoord]],
) -> dict[HexCoord, UnderworldRegion]:
    """Build UnderworldRegion objects from cave cluster data.

    Returns a dict keyed by canonical coord.
    """
    regions: dict[HexCoord, UnderworldRegion] = {}
    for canonical, members in clusters.items():
        size = len(members)
        regions[canonical] = UnderworldRegion(
            canonical_coord=canonical,
            member_coords=list(members),
            max_depth=max_depth_for_cluster(size),
        )
    return regions
