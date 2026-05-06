"""Builder / level walk → ``V5OpEntry(V5StampOp)``.

:func:`emit_stamps` walks the level directly to derive the three
texture-overlay stamp ops the v4 emit pipeline produces:

- ``GridLines`` (mirrors :func:`_emit_floor_grid_ir` — emitted
  whenever the level has any non-VOID tile).
- ``Cracks | Scratches`` (mirrors :func:`_emit_floor_detail_ir`
  — emitted when the floor-detail candidate set is non-empty,
  or when the wood-floor short-circuit fires).
- ``Ripples | LavaCracks`` (mirrors :func:`_emit_terrain_detail_ir`
  — emitted whenever the level has any WATER / LAVA / CHASM tile).
"""

from __future__ import annotations

from typing import Any

from nhc.rendering.ir._fb.V5Op import V5Op
from nhc.rendering.ir._fb.V5OpEntry import V5OpEntryT
from nhc.rendering.ir._fb.V5StampOp import V5StampOpT


# Decorator-bit registry — mirrors design/map_ir_v5.md §5 and the
# ``bit::`` constants on the Rust handler at
# ``transform/png/v5/stamp_op.rs``.
BIT_GRID_LINES = 1 << 0
BIT_CRACKS = 1 << 1
BIT_SCRATCHES = 1 << 2
BIT_RIPPLES = 1 << 3
BIT_LAVA_CRACKS = 1 << 4
BIT_MOSS = 1 << 5
BIT_BLOOD = 1 << 6
BIT_ASH = 1 << 7
BIT_PUDDLES = 1 << 8


def _wrap(stamp_op: V5StampOpT) -> V5OpEntryT:
    entry = V5OpEntryT()
    entry.opType = V5Op.V5StampOp
    entry.op = stamp_op
    return entry


def _make_stamp_op(*, region_ref: str, mask: int, seed: int) -> V5StampOpT:
    op = V5StampOpT()
    op.regionRef = region_ref
    op.subtractRegionRefs = []
    op.decoratorMask = mask
    op.density = 128
    op.seed = seed
    return op


def _dungeon_region_ref(ctx: Any) -> str:
    poly = getattr(ctx, "dungeon_poly", None)
    if poly is not None and not poly.is_empty:
        return "dungeon"
    return ""


def emit_stamps(builder: Any) -> list[V5OpEntryT]:
    """Walk builder.ctx + level to produce V5StampOp entries.

    Returns one stamp per layer that has work to do (GridLines,
    Cracks|Scratches, Ripples|LavaCracks). Defensive on synthetic
    fixture builders: skips entirely when the level lacks ``tiles``.
    """
    from nhc.dungeon.model import SurfaceType, Terrain
    from nhc.rendering._floor_layers import _floor_detail_candidates
    from nhc.rendering._svg_helpers import _is_door

    ctx = builder.ctx
    level = ctx.level
    tiles_grid = getattr(level, "tiles", None)
    if tiles_grid is None:
        return []

    result: list[V5OpEntryT] = []
    region_ref = _dungeon_region_ref(ctx)

    # GridLines — emitted whenever any non-VOID tile exists.
    has_grid_tile = False
    for y in range(level.height):
        for x in range(level.width):
            if level.tiles[y][x].terrain != Terrain.VOID:
                has_grid_tile = True
                break
        if has_grid_tile:
            break
    if has_grid_tile:
        result.append(_wrap(_make_stamp_op(
            region_ref=region_ref,
            mask=BIT_GRID_LINES,
            seed=41,
        )))

    # Cracks | Scratches — emitted when the floor-detail candidate
    # set is non-empty (non-wood path) or when the wood-floor short-
    # circuit fires.
    interior_finish = getattr(ctx, "interior_finish", "")
    if interior_finish == "wood":
        building_polygon = getattr(ctx, "building_polygon", None)
        wood_floor_tiles_present = False
        if building_polygon is None:
            for y in range(level.height):
                for x in range(level.width):
                    if level.tiles[y][x].terrain is Terrain.FLOOR:
                        wood_floor_tiles_present = True
                        break
                if wood_floor_tiles_present:
                    break
        emit_detail_stamp = (
            wood_floor_tiles_present or building_polygon is not None
        )
    else:
        emit_detail_stamp = bool(_floor_detail_candidates(level))
    if emit_detail_stamp:
        result.append(_wrap(_make_stamp_op(
            region_ref=region_ref,
            mask=BIT_CRACKS | BIT_SCRATCHES,
            seed=ctx.seed + 99,
        )))

    # Ripples | LavaCracks — emitted whenever any WATER / LAVA /
    # CHASM tile exists.
    has_terrain_detail = False
    for y in range(level.height):
        for x in range(level.width):
            t = level.tiles[y][x].terrain
            if t == Terrain.WATER or t == Terrain.LAVA or t == Terrain.CHASM:
                has_terrain_detail = True
                break
        if has_terrain_detail:
            break
    if has_terrain_detail:
        result.append(_wrap(_make_stamp_op(
            region_ref=region_ref,
            mask=BIT_RIPPLES | BIT_LAVA_CRACKS,
            seed=ctx.seed + 200,
        )))

    return result
