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

from nhc.rendering.ir._fb.Op import Op
from nhc.rendering.ir._fb.OpEntry import OpEntryT
from nhc.rendering.ir._fb.PaintOp import PaintOpT
from nhc.rendering.emit.materials import (
    EARTH_GRASS,
    LIQUID_LAVA,
    LIQUID_WATER,
    SPECIAL_CHASM,
    STONE_BRICK,
    STONE_BRICK_RUNNING_BOND,
    STONE_COBBLE_HERRINGBONE,
    STONE_COBBLESTONE,
    STONE_FIELDSTONE,
    STONE_FLAGSTONE,
    STONE_OPUS_ROMANO,
    material_cave,
    material_earth,
    material_liquid,
    material_plain,
    material_special,
    material_stone,
    material_wood,
)


def _wrap(paint_op: PaintOpT) -> OpEntryT:
    entry = OpEntryT()
    entry.opType = Op.PaintOp
    entry.op = paint_op
    return entry


def _make_paint_op(
    *, region_ref: str, material, subtract_region_refs: list[str] | None = None
) -> PaintOpT:
    op = PaintOpT()
    op.regionRef = region_ref
    op.subtractRegionRefs = list(subtract_region_refs or [])
    op.material = material
    return op


def emit_paints(builder: Any) -> list[OpEntryT]:
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

    # Pre-collect terrain + stone-decorator region ids registered by
    # ``_emit_floor_layers`` / ``emit_regions``. Each "<kind>.<i>" in
    # builder.regions corresponds to one disjoint cluster (water /
    # lava / chasm / grass / paved / brick / flagstone / opus_romano /
    # fieldstone) and gets one PaintOp here.
    terrain_region_ids: dict[str, list[str]] = {
        "water": [], "lava": [], "chasm": [], "grass": [],
        "paved": [], "brick": [], "flagstone": [],
        "opus_romano": [], "fieldstone": [],
    }
    for region in builder.regions:
        rid = region.id
        if isinstance(rid, bytes):
            rid = rid.decode()
        for prefix in terrain_region_ids:
            if rid.startswith(f"{prefix}."):
                terrain_region_ids[prefix].append(rid)
                break

    result: list[OpEntryT] = []

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

    # 3. Terrain regions — water / lava / chasm / grass clusters
    # picked up by emit_regions land here as PaintOps with the
    # canonical v5 family material. Mirrors the v4 TerrainTintOp's
    # translucent tint over the white floor; the v5 painter's
    # Liquid / Earth / Special families are responsible for the
    # actual color.
    for rid in terrain_region_ids["water"]:
        result.append(_wrap(_make_paint_op(
            region_ref=rid,
            material=material_liquid(style=LIQUID_WATER, seed=0),
        )))
    for rid in terrain_region_ids["lava"]:
        result.append(_wrap(_make_paint_op(
            region_ref=rid,
            material=material_liquid(style=LIQUID_LAVA, seed=0),
        )))
    for rid in terrain_region_ids["chasm"]:
        result.append(_wrap(_make_paint_op(
            region_ref=rid,
            material=material_special(style=SPECIAL_CHASM, seed=0),
        )))
    for rid in terrain_region_ids["grass"]:
        result.append(_wrap(_make_paint_op(
            region_ref=rid,
            material=material_earth(style=EARTH_GRASS, seed=0),
        )))

    # 4. Corridor (merged) — gated identically to emit_regions and
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

    # 5. Stone-variant decorators — emit one PaintOp per disjoint
    # ``<prefix>.<i>`` region registered by ``_emit_floor_layers``.
    # Gated on the wood short-circuit (the v4 emit returns before the
    # decorator pass when ``interior_finish == "wood"``).
    if not is_wood:
        deco_seed = ctx.seed + 333
        for region_prefix, style, sub_pattern in (
            ("paved", STONE_COBBLESTONE, STONE_COBBLE_HERRINGBONE),
            ("brick", STONE_BRICK, STONE_BRICK_RUNNING_BOND),
            ("flagstone", STONE_FLAGSTONE, 0),
            ("opus_romano", STONE_OPUS_ROMANO, 0),
            ("fieldstone", STONE_FIELDSTONE, 0),
        ):
            for rid in terrain_region_ids[region_prefix]:
                result.append(_wrap(_make_paint_op(
                    region_ref=rid,
                    material=material_stone(
                        style=style,
                        sub_pattern=sub_pattern,
                        seed=deco_seed,
                    ),
                )))

    return result

