"""Shared floor-builder helper.

Each site's ``_build_<arch>_floor()`` runs the same pipeline: carve
footprint, run a partitioner, apply the plan, patch tags, close
the shell. This helper bundles that pipeline so a partitioner
swap (M6-M12) touches one place per site rather than eight.
"""

from __future__ import annotations

import random

from nhc.dungeon.interior._apply import apply_plan
from nhc.dungeon.interior.protocol import Partitioner, PartitionerConfig
from nhc.dungeon.model import Level, Rect, RoomShape, Terrain, Tile
from nhc.dungeon.sites._shell import compose_shell


def build_building_floor(
    *,
    building_id: str,
    floor_idx: int,
    base_shape: RoomShape,
    base_rect: Rect,
    n_floors: int,
    rng: random.Random,
    archetype: str,
    tags: list[str],
    partitioner: Partitioner,
    required_walkable: frozenset[tuple[int, int]] = frozenset(),
) -> Level:
    """Run the partitioner pipeline for a single building floor.

    Site-specific post-processing (``level.interior_floor``,
    entity placement, etc.) stays in the site assembler — this
    helper covers the layout-only pass that every archetype
    shares.
    """
    w = base_rect.x + base_rect.width + 2
    h = base_rect.y + base_rect.height + 2
    level = Level.create_empty(
        f"{building_id}_f{floor_idx}",
        f"{building_id} floor {floor_idx}",
        floor_idx + 1, w, h,
    )

    footprint = base_shape.floor_tiles(base_rect)
    for (x, y) in footprint:
        level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)

    cfg = PartitionerConfig(
        footprint=base_rect,
        shape=base_shape,
        floor_index=floor_idx,
        n_floors=n_floors,
        rng=rng,
        archetype=archetype,
        required_walkable=required_walkable,
    )
    plan = partitioner.plan(cfg)
    apply_plan(level, plan)

    entrance_tags = ["entrance"] if floor_idx == 0 else []
    plan.rooms[0].tags = list(tags) + entrance_tags
    level.rooms = plan.rooms

    compose_shell(level, {building_id: footprint})

    level.building_id = building_id
    level.floor_index = floor_idx
    return level
