"""Shared floor-builder helper.

Each site's ``_build_<arch>_floor()`` runs the same pipeline: carve
footprint, run a partitioner, apply the plan, patch tags, close
the shell. This helper bundles that pipeline so a partitioner
swap (M6-M12) touches one place per site rather than eight.
"""

from __future__ import annotations

import random

from nhc.dungeon.interior._apply import apply_plan
from nhc.dungeon.interior.divided import DividedPartitioner
from nhc.dungeon.interior.lshape import LShapePartitioner
from nhc.dungeon.interior.protocol import Partitioner, PartitionerConfig
from nhc.dungeon.interior.rect_bsp import RectBSPPartitioner
from nhc.dungeon.interior.registry import ARCHETYPE_CONFIG, ArchetypeSpec
from nhc.dungeon.interior.sector import SectorPartitioner
from nhc.dungeon.interior.single_room import SingleRoomPartitioner
from nhc.dungeon.interior.temple import TemplePartitioner
from nhc.dungeon.model import Level, Rect, RoomShape, Terrain, Tile
from nhc.dungeon.sites._shell import compose_shell


def resolve_partitioner(spec: ArchetypeSpec) -> Partitioner:
    """Map an :class:`ArchetypeSpec` to a partitioner instance.

    Unknown partitioner names raise ``ValueError``. See
    ``design/building_interiors.md`` — loud failure on typos.
    """
    name = spec.partitioner
    if name == "single_room":
        return SingleRoomPartitioner()
    if name == "divided":
        return DividedPartitioner()
    if name == "rect_bsp":
        return RectBSPPartitioner(mode=spec.bsp_mode)
    if name == "sector":
        return SectorPartitioner(mode=spec.sector_mode)
    if name == "temple":
        return TemplePartitioner()
    if name == "lshape":
        return LShapePartitioner()
    raise ValueError(
        f"unknown partitioner {name!r} for archetype spec"
    )


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
    partitioner: Partitioner | None = None,
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

    if partitioner is None:
        spec = ARCHETYPE_CONFIG[archetype]
        partitioner = resolve_partitioner(spec)
        corridor_width = spec.corridor_width
        min_room = spec.min_room
        padding = spec.padding
    else:
        corridor_width = 1
        min_room = 3
        padding = 1

    cfg = PartitionerConfig(
        footprint=base_rect,
        shape=base_shape,
        floor_index=floor_idx,
        n_floors=n_floors,
        rng=rng,
        archetype=archetype,
        required_walkable=required_walkable,
        min_room=min_room,
        padding=padding,
        corridor_width=corridor_width,
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
