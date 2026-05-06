"""Builder / level walk → ``V5OpEntry(V5PaintOp)``.

:func:`emit_paints` walks ``builder.ctx`` + ``level`` + per-tile
decorator predicates to produce the v5 PaintOp stream — mirrors
the source logic of the FloorOp + DecoratorOp emission branches in
:func:`nhc.rendering._floor_layers._emit_walls_and_floors_ir` /
:func:`_emit_floor_detail_ir`.

Emission order matches the v4 pipeline so PSNR parity with the
existing translator stays tight:

1. Cave systems (one V5PaintOp(Cave) per disjoint cave system).
2. Per non-cave room (Plain family).
3. Merged corridor region (Plain family).
4. Building polygon base fill (Wood or Plain).
5. Per-tile wood floor (Wood family) when ``is_wood`` and no
   building polygon is set.
6. Stone-variant decorators (per-style V5PaintOp(Stone)).
"""

from __future__ import annotations

from typing import Any

from nhc.rendering.ir._fb.V5Op import V5Op
from nhc.rendering.ir._fb.V5OpEntry import V5OpEntryT
from nhc.rendering.ir._fb.V5PaintOp import V5PaintOpT
from nhc.rendering.v5_emit.materials import (
    STONE_BRICK,
    STONE_BRICK_RUNNING_BOND,
    STONE_COBBLE_HERRINGBONE,
    STONE_COBBLESTONE,
    STONE_FIELDSTONE,
    STONE_FLAGSTONE,
    STONE_OPUS_ROMANO,
    material_cave,
    material_plain,
    material_stone,
    material_wood,
)


def _wrap(paint_op: V5PaintOpT) -> V5OpEntryT:
    entry = V5OpEntryT()
    entry.opType = V5Op.V5PaintOp
    entry.op = paint_op
    return entry


def _make_paint_op(
    *, region_ref: str, material, subtract_region_refs: list[str] | None = None
) -> V5PaintOpT:
    op = V5PaintOpT()
    op.regionRef = region_ref
    op.subtractRegionRefs = list(subtract_region_refs or [])
    op.material = material
    return op


def emit_paints(builder: Any) -> list[V5OpEntryT]:
    """Walk builder.ctx + level to produce V5PaintOp entries.

    Defensive on synthetic fixture builders: returns an empty list
    when ``level.tiles`` is missing.
    """
    from nhc.dungeon.generators.cellular import CaveShape
    from nhc.dungeon.model import (
        CircleShape, CrossShape, HybridShape, LShape, OctagonShape,
        PillShape, RectShape, TempleShape,
    )
    from nhc.dungeon.model import Terrain
    from nhc.rendering._floor_detail import (
        _is_brick_tile, _is_cobble_tile, _is_field_overlay_tile,
        _is_flagstone_tile, _is_opus_romano_tile,
    )
    from nhc.rendering._floor_layers import (
        _collect_cave_systems, _collect_corridor_components,
        _collect_corridor_tiles,
    )
    from nhc.rendering.ir_emitter import _corridor_component_rings

    ctx = builder.ctx
    level = ctx.level
    tiles_grid = getattr(level, "tiles", None)
    if tiles_grid is None:
        return []

    cave_tiles: set[tuple[int, int]] = (
        set(ctx.cave_tiles) if getattr(ctx, "cave_tiles", None) else set()
    )
    is_wood = getattr(ctx, "interior_finish", "") == "wood"
    suppress_rect_rooms = bool(getattr(ctx, "building_polygon", None))
    cave_region_rooms: set[int] = set()
    if cave_tiles:
        for idx, room in enumerate(level.rooms):
            if isinstance(room.shape, CaveShape):
                cave_region_rooms.add(idx)

    result: list[V5OpEntryT] = []

    # 1. Cave systems.
    if cave_tiles:
        from nhc.rendering._cave_geometry import _cave_raw_exterior_coords
        for i, tile_group in enumerate(_collect_cave_systems(cave_tiles)):
            coords = _cave_raw_exterior_coords(tile_group)
            if not coords or len(coords) < 4:
                continue
            # Translator-side parity: v4 FloorOp(CaveFloor) → Cave-Limestone.
            result.append(_wrap(_make_paint_op(
                region_ref=f"cave.{i}",
                material=material_cave(seed=0),
            )))

    # 2. Per-room (excluding cave rooms; suppressed when building
    # polygon is set).
    for idx, room in enumerate(level.rooms):
        if idx in cave_region_rooms:
            continue
        if suppress_rect_rooms:
            continue
        shape = room.shape
        if not isinstance(shape, (
            RectShape, OctagonShape, LShape, TempleShape,
            CircleShape, PillShape, CrossShape, HybridShape,
        )):
            continue
        result.append(_wrap(_make_paint_op(
            region_ref=room.id,
            material=material_plain(seed=0),
        )))

    # 3. Corridor (merged) — gated identically to emit_regions and
    # _emit_walls_and_floors_ir's corridor block.
    corridor_tiles = _collect_corridor_tiles(level, cave_tiles)
    if corridor_tiles:
        components = _collect_corridor_components(corridor_tiles)
        has_valid_ring = any(
            ring_coords and len(ring_coords) >= 4
            for comp in components
            for ring_coords, _ in _corridor_component_rings(comp)
        )
        if has_valid_ring:
            result.append(_wrap(_make_paint_op(
                region_ref="corridor",
                material=material_plain(seed=0),
            )))

    # 4. Building polygon base fill.
    building_polygon = getattr(ctx, "building_polygon", None)
    if building_polygon:
        material = material_wood(seed=0) if is_wood else material_plain(seed=0)
        result.append(_wrap(_make_paint_op(
            region_ref="",
            material=material,
        )))
    elif is_wood:
        # Per-tile wood floor coverage when no polygon set.
        for y in range(level.height):
            for x in range(level.width):
                tile = level.tiles[y][x]
                if tile.terrain is not Terrain.FLOOR:
                    continue
                if (x, y) in cave_tiles:
                    continue
                result.append(_wrap(_make_paint_op(
                    region_ref="",
                    material=material_wood(seed=0),
                )))

    # 5. Stone-variant decorators — gated on the wood short-circuit
    # in v4 emit (which returns before the decorator pass when
    # interior_finish == "wood").
    if not is_wood:
        deco_seed = ctx.seed + 333
        cobble_hits = False
        brick_hits = False
        flagstone_hits = False
        opus_romano_hits = False
        field_stone_hits = False
        for y in range(level.height):
            for x in range(level.width):
                if not cobble_hits and _is_cobble_tile(level, x, y):
                    cobble_hits = True
                if not brick_hits and _is_brick_tile(level, x, y):
                    brick_hits = True
                if not flagstone_hits and _is_flagstone_tile(level, x, y):
                    flagstone_hits = True
                if not opus_romano_hits and _is_opus_romano_tile(level, x, y):
                    opus_romano_hits = True
                if not field_stone_hits and _is_field_overlay_tile(level, x, y):
                    field_stone_hits = True
                if (
                    cobble_hits and brick_hits and flagstone_hits
                    and opus_romano_hits and field_stone_hits
                ):
                    break
            if (
                cobble_hits and brick_hits and flagstone_hits
                and opus_romano_hits and field_stone_hits
            ):
                break

        if cobble_hits:
            result.append(_wrap(_make_paint_op(
                region_ref="",
                material=material_stone(
                    style=STONE_COBBLESTONE,
                    sub_pattern=STONE_COBBLE_HERRINGBONE,
                    seed=deco_seed,
                ),
            )))
        if brick_hits:
            result.append(_wrap(_make_paint_op(
                region_ref="",
                material=material_stone(
                    style=STONE_BRICK,
                    sub_pattern=STONE_BRICK_RUNNING_BOND,
                    seed=deco_seed,
                ),
            )))
        if flagstone_hits:
            result.append(_wrap(_make_paint_op(
                region_ref="",
                material=material_stone(
                    style=STONE_FLAGSTONE, seed=deco_seed,
                ),
            )))
        if opus_romano_hits:
            result.append(_wrap(_make_paint_op(
                region_ref="",
                material=material_stone(
                    style=STONE_OPUS_ROMANO, seed=deco_seed,
                ),
            )))
        if field_stone_hits:
            result.append(_wrap(_make_paint_op(
                region_ref="",
                material=material_stone(
                    style=STONE_FIELDSTONE, seed=deco_seed,
                ),
            )))

    return result

