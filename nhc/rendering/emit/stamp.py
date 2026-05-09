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

from nhc.rendering.ir._fb.Op import Op
from nhc.rendering.ir._fb.OpEntry import OpEntryT
from nhc.rendering.ir._fb.StampOp import StampOpT


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
# Post-Phase-5 deferred-polish additions.
BIT_FROST = 1 << 9
BIT_MOLD = 1 << 10
BIT_LEAVES = 1 << 11
BIT_SNOW = 1 << 12
BIT_SAND_DRIFT = 1 << 13
BIT_POLLEN = 1 << 14
BIT_STAINS = 1 << 15
BIT_INSCRIPTIONS = 1 << 16
BIT_FOOTPRINTS = 1 << 17


def _wrap(stamp_op: StampOpT) -> OpEntryT:
    entry = OpEntryT()
    entry.opType = Op.StampOp
    entry.op = stamp_op
    return entry


def _make_stamp_op(*, region_ref: str, mask: int, seed: int) -> StampOpT:
    op = StampOpT()
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


def _corridor_region_exists(builder: Any) -> bool:
    """True iff ``emit_regions`` registered a ``corridor`` region.

    The corridor region is built per-level when at least one floor
    tile is on a corridor / door (see ``ir_emitter._corridor_*``
    helpers). Synthetic / room-only fixtures don't have one.
    """
    for region in builder.regions:
        rid = region.id
        if isinstance(rid, bytes):
            rid = rid.decode()
        if rid == "corridor":
            return True
    return False


def emit_stamps(builder: Any) -> list[OpEntryT]:
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

    result: list[OpEntryT] = []
    region_ref = _dungeon_region_ref(ctx)
    has_corridor = _corridor_region_exists(builder)

    # GridLines — emitted whenever any non-VOID tile exists. The
    # ``dungeon`` region polygon covers room interiors only;
    # corridors are a separate multi-ring region (see
    # ``_dungeon_polygon._build_dungeon_polygon`` docstring), so we
    # need a SECOND stamp targeting ``corridor`` for the corridor
    # grid + decoration coverage to land.
    has_grid_tile = False
    for y in range(level.height):
        for x in range(level.width):
            if level.tiles[y][x].terrain != Terrain.VOID:
                has_grid_tile = True
                break
        if has_grid_tile:
            break
    if has_grid_tile:
        if region_ref:
            result.append(_wrap(_make_stamp_op(
                region_ref=region_ref,
                mask=BIT_GRID_LINES,
                seed=41,
            )))
        if has_corridor:
            result.append(_wrap(_make_stamp_op(
                region_ref="corridor",
                mask=BIT_GRID_LINES,
                seed=41,
            )))

    # Cracks | Scratches — emitted when the floor-detail candidate
    # set is non-empty (non-wood path) or when the wood-floor short-
    # circuit fires. Same dungeon / corridor split as GridLines so
    # corridor floors carry the same scratches + cracks decoration.
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
        if region_ref:
            result.append(_wrap(_make_stamp_op(
                region_ref=region_ref,
                mask=BIT_CRACKS | BIT_SCRATCHES,
                seed=ctx.seed + 99,
            )))
        if has_corridor:
            result.append(_wrap(_make_stamp_op(
                region_ref="corridor",
                mask=BIT_CRACKS | BIT_SCRATCHES,
                seed=ctx.seed + 99,
            )))

    # Ripples — emitted per WATER region (Liquid:Water substrate
    # decoration). LavaCracks — emitted per LAVA region (Liquid:Lava
    # substrate decoration). Chasm regions get neither — the Special
    # family's substrate painter renders depth without a decorator
    # bit. Pre-fix this was one StampOp targeting the ``dungeon``
    # polygon with both bits unioned, so every dry stone floor tile
    # got water ripples + lava cracks stamped on top.
    for region in builder.regions:
        rid = region.id
        if isinstance(rid, bytes):
            rid = rid.decode()
        if rid.startswith("water."):
            result.append(_wrap(_make_stamp_op(
                region_ref=rid,
                mask=BIT_RIPPLES,
                seed=ctx.seed + 200,
            )))
        elif rid.startswith("lava."):
            result.append(_wrap(_make_stamp_op(
                region_ref=rid,
                mask=BIT_LAVA_CRACKS,
                seed=ctx.seed + 200,
            )))

    return result
